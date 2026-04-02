"""Query loop — the heart of the agent engine.

An async generator that drives the model through turns of:
  pre-model governance -> call model (streaming) -> error detection
  -> tool execution -> state transition -> next turn or stop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from context.prompt import build_system_prompt
from engine.state import (
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
) -> AsyncGenerator[Event, None]:
    """Main query loop — async generator yielding Events.

    Args:
        messages: Initial conversation messages (Anthropic format).
        role_config: Role configuration for this agent instance.
        tools: Anthropic API tool definitions (JSON Schema dicts).
        tool_executor: Callback to execute tool calls. None = no tools.
        abort_signal: Set this event to abort the loop.
        max_turns: Override role_config.max_turns.

    Yields:
        Event objects (TextEvent, ToolUseEvent, ToolResultEvent, etc.)
    """
    client = anthropic.AsyncAnthropic()
    effective_max_turns = max_turns or role_config.max_turns
    system_prompt = build_system_prompt(
        role_config,
        tool_names=[t["name"] for t in tools] if tools else None,
    )

    state = LoopState(messages=tuple(messages))

    while True:
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

        # --- Phase A: Pre-model governance (stub — Phase 3 fills this) ---
        # Future: check token budget, trigger autocompact

        # --- Phase B: Call model (streaming) ---
        accumulated_text = ""
        tool_use_blocks: list[dict[str, Any]] = []

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

        except anthropic.APIStatusError as e:
            yield ErrorEvent(error=str(e), recoverable=False)
            yield DoneEvent(
                reason="error",
                turn_count=state.turn_count,
                messages=state.messages,
            )
            return

        # Update token tracking from response usage
        state = evolve(
            state,
            input_tokens_used=response.usage.input_tokens,
            output_tokens_used=response.usage.output_tokens,
            turn_count=state.turn_count + 1,
        )

        # Extract tool_use blocks from response content
        for block in response.content:
            if block.type == "tool_use":
                tool_use_blocks.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        # --- Phase C: Error detection (basic — Phase 3 enhances) ---
        # Future: handle prompt_too_long, max_output_tokens, API errors

        # --- Phase D: Tool execution ---
        if tool_use_blocks and tool_executor:
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
            continue

        # --- Phase E: No tool use = end turn ---
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
