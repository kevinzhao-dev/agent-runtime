"""Recovery strategies for the query loop.

Pure functions that take state and return new state (or None if unrecoverable).
The loop owns control flow — these functions only compute the recovery action.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from context.budget import TokenBudget
from context.compact import MAX_CONSECUTIVE_COMPACT_FAILURES, compact_conversation
from engine.state import CompactTracking, LoopState, evolve

MAX_OUTPUT_RECOVERY_LIMIT = 5
API_RETRY_MAX = 5

# HTTP status codes that are retryable
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float = 0.0
    reason: str = ""


async def handle_prompt_too_long(
    state: LoopState,
    model: str,
) -> LoopState | None:
    """Handle prompt-too-long error.

    Strategy (increasing destructiveness):
    1. If under circuit breaker limit: compact conversation
    2. If compact fails: return None (unrecoverable)
    """
    tracking = state.compact_tracking
    if tracking.consecutive_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
        return None  # Circuit breaker tripped

    try:
        result = await compact_conversation(
            messages=list(state.messages),
            model=model,
            tokens_before=state.input_tokens_used,
        )
        return evolve(
            state,
            messages=tuple(result.post_compact_messages),
            compact_tracking=CompactTracking(
                compact_count=tracking.compact_count + 1,
                consecutive_failures=0,
                last_compact_token_count=result.tokens_before,
            ),
        )
    except Exception:
        return evolve(
            state,
            compact_tracking=CompactTracking(
                compact_count=tracking.compact_count,
                consecutive_failures=tracking.consecutive_failures + 1,
                last_compact_token_count=tracking.last_compact_token_count,
            ),
        )


def handle_max_output_tokens(
    state: LoopState,
    partial_response_text: str,
) -> LoopState | None:
    """Handle max_tokens stop_reason by injecting a continuation message.

    Returns new state with continuation prompt, or None if limit exceeded.
    """
    if state.max_output_recoveries >= MAX_OUTPUT_RECOVERY_LIMIT:
        return None  # Circuit breaker

    # Build assistant message from partial response
    assistant_msg: dict[str, Any] = {"role": "assistant", "content": partial_response_text}

    # Inject continuation prompt
    continuation_msg: dict[str, Any] = {
        "role": "user",
        "content": "[System: Your response was truncated. Continue from where you left off.]",
    }

    return evolve(
        state,
        messages=state.messages + (assistant_msg, continuation_msg),
        max_output_recoveries=state.max_output_recoveries + 1,
    )


def handle_api_error(error: Exception, attempt: int) -> RetryDecision:
    """Compute retry decision for API errors with exponential backoff.

    Only retries on transient errors (429, 5xx). Non-retryable errors
    (400, 401, 403) return should_retry=False immediately.
    """
    if attempt >= API_RETRY_MAX:
        return RetryDecision(
            should_retry=False,
            reason=f"Max retries ({API_RETRY_MAX}) exceeded",
        )

    # Check if the error has a status code
    status_code = getattr(error, "status_code", None)
    if status_code is not None and status_code not in RETRYABLE_STATUS_CODES:
        return RetryDecision(
            should_retry=False,
            reason=f"Non-retryable status code: {status_code}",
        )

    # Exponential backoff with jitter
    base_delay = 2 ** attempt  # 1, 2, 4, 8, 16
    jitter = random.uniform(0, base_delay * 0.5)
    delay = base_delay + jitter

    return RetryDecision(
        should_retry=True,
        delay_seconds=delay,
        reason=f"Retry {attempt + 1}/{API_RETRY_MAX} after {delay:.1f}s",
    )
