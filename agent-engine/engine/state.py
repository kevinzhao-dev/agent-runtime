"""State types for the agent engine.

All cross-turn state is held in frozen dataclasses. State transitions
produce new objects via evolve(), keeping the causal chain explicit.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Events — yielded by query_loop to consumers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextEvent:
    """Streaming text delta from the model."""
    text: str


@dataclass(frozen=True)
class ToolUseEvent:
    """Model requested a tool call."""
    tool_name: str
    tool_id: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultEvent:
    """Result of a tool execution."""
    tool_id: str
    content: str
    is_error: bool


@dataclass(frozen=True)
class CompactEvent:
    """Context was compacted."""
    summary: str
    tokens_before: int
    tokens_after: int


@dataclass(frozen=True)
class ErrorEvent:
    """An error occurred."""
    error: str
    recoverable: bool


@dataclass(frozen=True)
class DoneEvent:
    """Loop finished."""
    reason: str  # end_turn | max_turns | abort | circuit_break | error
    turn_count: int
    messages: tuple[dict[str, Any], ...] = ()


Event = TextEvent | ToolUseEvent | ToolResultEvent | CompactEvent | ErrorEvent | DoneEvent


# ---------------------------------------------------------------------------
# Transition reasons
# ---------------------------------------------------------------------------

class TransitionReason(str, Enum):
    NEXT_TURN = "next_turn"
    REACTIVE_COMPACT_RETRY = "reactive_compact_retry"
    MAX_OUTPUT_RECOVERY = "max_output_recovery"
    API_RETRY = "api_retry"
    ABORT = "abort"
    CIRCUIT_BREAK = "circuit_break"
    MAX_TURNS = "max_turns"
    DONE = "done"


# ---------------------------------------------------------------------------
# Compact tracking
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompactTracking:
    compact_count: int = 0
    consecutive_failures: int = 0
    last_compact_token_count: int = 0


# ---------------------------------------------------------------------------
# Loop state — the single source of truth across turns
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopState:
    messages: tuple[dict[str, Any], ...]
    turn_count: int = 0
    compact_tracking: CompactTracking = field(default_factory=CompactTracking)
    recovery_attempts: int = 0
    max_output_recoveries: int = 0
    api_retry_count: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    last_transition: TransitionReason | None = None


def evolve(state: LoopState, **changes: Any) -> LoopState:
    """Create a new LoopState with specified fields changed."""
    return dataclasses.replace(state, **changes)
