"""Query loop — the heart of the agent engine.

An async generator that drives the model through turns of:
  pre-model governance -> call model (streaming) -> error detection
  -> tool execution -> state transition -> next turn or stop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anthropic

logger = logging.getLogger("agent_engine.loop")

from context.budget import TokenBudget
from context.compact import MAX_CONSECUTIVE_COMPACT_FAILURES, compact_conversation
from context.prompt import build_system_prompt
from engine.recovery import (
    handle_api_error,
    handle_max_output_tokens,
    handle_prompt_too_long,
)
from engine.state import (
    CompactEvent,
    CompactTracking,
    DoneEvent,
    ErrorEvent,
    Event,
    LoopState,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
    TransitionReason,
    evolve,
)
from roles.config import DEFAULT_ROLE, RoleConfig


@dataclass
class ToolResult:
    """Result returned by a tool executor."""
    content: str
    is_error: bool = False


# Type for the tool executor callback injected by the tool system.
# (tool_name, tool_id, input_dict) -> ToolResult
ToolExecutor = Callable[[str, str, dict[str, Any]], Awaitable[ToolResult]]


async def query_loop(
    *,
    messages: list[dict[str, Any]],
    role_config: RoleConfig = DEFAULT_ROLE,
    tools: list[dict[str, Any]] | None = None,
    tool_executor: ToolExecutor | None = None,
    abort_signal: asyncio.Event | None = None,
    max_turns: int | None = None,
    token_budget: TokenBudget | None = None,
    client: Any | None = None,
) -> AsyncGenerator[Event, None]:
    """Main query loop — async generator yielding Events.

    Args:
        messages: Initial conversation messages (Anthropic format).
        role_config: Role configuration for this agent instance.
        tools: Anthropic API tool definitions (JSON Schema dicts).
        tool_executor: Callback to execute tool calls. None = no tools.
        abort_signal: Set this event to abort the loop.
        max_turns: Override role_config.max_turns.
        token_budget: Token budget for context governance.
        client: Anthropic client instance. If None, creates AsyncAnthropic().
            Pass a mock/dry-run client for testing.

    Yields:
        Event objects (TextEvent, ToolUseEvent, ToolResultEvent, etc.)
    """
    if client is None:
        client = anthropic.AsyncAnthropic()
    effective_max_turns = max_turns or role_config.max_turns
    system_prompt = build_system_prompt(
        role_config,
        tool_names=[t["name"] for t in tools] if tools else None,
    )

    budget = token_budget or TokenBudget()
    state = LoopState(messages=tuple(messages))

    logger.info(
        "loop_start role=%s model=%s max_turns=%d tools=%s",
        role_config.name, role_config.model, effective_max_turns,
        [t["name"] for t in tools] if tools else [],
    )

    while True:
        logger.debug(
            "turn_begin turn=%d messages=%d input_tokens=%d",
            state.turn_count, len(state.messages), budget.current_input_tokens,
        )

        # --- Check abort ---
        if abort_signal and abort_signal.is_set():
            yield DoneEvent(
                reason="abort",
                turn_count=state.turn_count,
                messages=state.messages,
            )
            return

        # --- Check max turns ---
        if state.turn_count >= effective_max_turns:
            yield DoneEvent(
                reason="max_turns",
                turn_count=state.turn_count,
                messages=state.messages,
            )
            return

        # --- Phase A: Pre-model governance ---
        if budget.should_compact() and state.turn_count > 0:
            tracking = state.compact_tracking
            if tracking.consecutive_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
                yield ErrorEvent(
                    error="Compact circuit breaker: too many consecutive failures",
                    recoverable=False,
                )
                yield DoneEvent(
                    reason="circuit_break",
                    turn_count=state.turn_count,
                    messages=state.messages,
                )
                return

            try:
                result = await compact_conversation(
                    messages=list(state.messages),
                    model=role_config.model,
                    tokens_before=budget.current_input_tokens,
                )
                yield CompactEvent(
                    summary=result.summary_message.get("content", "")[:200],
                    tokens_before=result.tokens_before,
                    tokens_after=result.tokens_after,
                )
                state = evolve(
                    state,
                    messages=tuple(result.post_compact_messages),
                    compact_tracking=CompactTracking(
                        compact_count=tracking.compact_count + 1,
                        consecutive_failures=0,
                        last_compact_token_count=budget.current_input_tokens,
                    ),
                    last_transition=TransitionReason.REACTIVE_COMPACT_RETRY,
                )
                # Budget will be updated from next API response
                continue
            except Exception as e:
                state = evolve(
                    state,
                    compact_tracking=CompactTracking(
                        compact_count=tracking.compact_count,
                        consecutive_failures=tracking.consecutive_failures + 1,
                        last_compact_token_count=tracking.last_compact_token_count,
                    ),
                )
                yield ErrorEvent(error=f"Compact failed: {e}", recoverable=True)
                # Continue to try the model call anyway

        # --- Phase B: Call model (streaming) ---
        logger.debug("phase_b call_model model=%s", role_config.model)
        accumulated_text = ""
        tool_use_blocks: list[dict[str, Any]] = []
        response = None

        try:
            api_kwargs: dict[str, Any] = {
                "model": role_config.model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": list(state.messages),
            }
            if tools:
                api_kwargs["tools"] = tools

            async with client.messages.stream(**api_kwargs) as stream:
                async for event in stream:
                    # Stream text deltas
                    if (
                        event.type == "content_block_delta"
                        and hasattr(event.delta, "text")
                    ):
                        yield TextEvent(text=event.delta.text)
                        accumulated_text += event.delta.text

                response = await stream.get_final_message()

        except anthropic.BadRequestError as e:
            # Possibly prompt-too-long
            if "prompt is too long" in str(e).lower():
                new_state = await handle_prompt_too_long(state, role_config.model)
                if new_state is None:
                    yield ErrorEvent(error="Unrecoverable: prompt too long", recoverable=False)
                    yield DoneEvent(reason="error", turn_count=state.turn_count, messages=state.messages)
                    return
                state = new_state
                yield ErrorEvent(error="Prompt too long — compacted, retrying", recoverable=True)
                continue
            else:
                yield ErrorEvent(error=str(e), recoverable=False)
                yield DoneEvent(reason="error", turn_count=state.turn_count, messages=state.messages)
                return

        except anthropic.APIStatusError as e:
            # Retryable API errors (429, 5xx)
            decision = handle_api_error(e, state.api_retry_count)
            if decision.should_retry:
                yield ErrorEvent(error=f"API error: {decision.reason}", recoverable=True)
                await asyncio.sleep(decision.delay_seconds)
                state = evolve(state, api_retry_count=state.api_retry_count + 1)
                continue
            else:
                yield ErrorEvent(error=f"API error (not retrying): {decision.reason}", recoverable=False)
                yield DoneEvent(reason="error", turn_count=state.turn_count, messages=state.messages)
                return

        # Update token tracking from response usage
        logger.info(
            "model_response turn=%d stop_reason=%s input_tokens=%d output_tokens=%d tool_calls=%d text_len=%d",
            state.turn_count, response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
            len(tool_use_blocks), len(accumulated_text),
        )
        budget = budget.update_from_usage({
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        })
        state = evolve(
            state,
            input_tokens_used=response.usage.input_tokens,
            output_tokens_used=response.usage.output_tokens,
            turn_count=state.turn_count + 1,
            api_retry_count=0,  # Reset on success
        )

        # Extract tool_use blocks from response content
        for block in response.content:
            if block.type == "tool_use":
                tool_use_blocks.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        # --- Phase C: Error detection — max output tokens ---
        if response.stop_reason == "max_tokens":
            new_state = handle_max_output_tokens(state, accumulated_text)
            if new_state is None:
                yield ErrorEvent(error="Max output recovery limit exceeded", recoverable=False)
                yield DoneEvent(reason="circuit_break", turn_count=state.turn_count, messages=state.messages)
                return
            state = new_state
            yield ErrorEvent(error="Output truncated — continuing", recoverable=True)
            continue

        # --- Phase D: Tool execution ---
        if tool_use_blocks and tool_executor:
            logger.info("phase_d tool_execution count=%d", len(tool_use_blocks))
            # Build assistant message from response content
            assistant_content: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            assistant_msg = {"role": "assistant", "content": assistant_content}

            # Execute each tool and collect results
            tool_results: list[dict[str, Any]] = []
            for tool_block in tool_use_blocks:
                yield ToolUseEvent(
                    tool_name=tool_block["name"],
                    tool_id=tool_block["id"],
                    input=tool_block["input"],
                )

                result = await tool_executor(
                    tool_block["name"],
                    tool_block["id"],
                    tool_block["input"],
                )

                yield ToolResultEvent(
                    tool_id=tool_block["id"],
                    content=result.content,
                    is_error=result.is_error,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block["id"],
                    "content": result.content,
                    **({"is_error": True} if result.is_error else {}),
                })

            tool_result_msg = {"role": "user", "content": tool_results}

            state = evolve(
                state,
                messages=state.messages + (assistant_msg, tool_result_msg),
                last_transition=TransitionReason.NEXT_TURN,
            )
            logger.debug("transition reason=NEXT_TURN messages=%d", len(state.messages))
            continue

        # --- Phase E: No tool use = end turn ---
        logger.info("phase_e end_turn turn=%d", state.turn_count)
        assistant_msg = {"role": "assistant", "content": accumulated_text}
        state = evolve(
            state,
            messages=state.messages + (assistant_msg,),
            last_transition=TransitionReason.DONE,
        )

        yield DoneEvent(
            reason="end_turn",
            turn_count=state.turn_count,
            messages=state.messages,
        )
        return
