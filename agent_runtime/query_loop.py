"""Core query loop — the heartbeat of the agent runtime.

The system is a `while` loop. The model call is one step inside it,
not the system itself. Context governance precedes model reasoning.

Yields an async stream of typed Events for the caller to consume.
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Callable, Generator

from agent_runtime.models import (
    Event,
    FinalEvent,
    RecoveryEvent,
    SessionState,
    TextDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnConfig,
    assistant_message,
    tool_result_message,
    user_message,
)
from agent_runtime.provider import AssistantTurn, TextChunk, ThinkingChunk
from agent_runtime.tools.base import ToolRegistry, registry as default_registry


# ── Mock Model Adapter (for testing without API) ─────────────────────────

class MockModelAdapter:
    """Deterministic model adapter for testing the loop mechanics.

    Accepts a list of AssistantTurn objects to yield in sequence.
    Each call to `stream()` returns the next turn.
    """

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self._index = 0

    def stream(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]] | None = None,
        max_tokens: int = 8192,
        config: dict[str, Any] | None = None,
    ) -> Generator[TextChunk | ThinkingChunk | AssistantTurn, None, None]:
        if self._index >= len(self._turns):
            yield AssistantTurn("No more mock turns.", [], 0, 0)
            return

        turn = self._turns[self._index]
        self._index += 1

        # Simulate streaming: yield text as a single chunk, then the turn
        if turn.text:
            yield TextChunk(turn.text)
        yield turn


# ── Tool Executor Protocol ────────────────────────────────────────────────

ToolExecutor = Callable[
    [str, dict[str, Any], SessionState, TurnConfig],  # name, input, state, config
    str,  # output
]

# Permission callback: given tool_name and input, returns True if allowed.
PermissionCallback = Callable[[str, dict[str, Any]], bool]


def _auto_permission(tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Default permission: low-risk auto-allow, high-risk deny."""
    return not default_registry.is_high_risk(tool_name)


def _noop_tool_executor(
    name: str,
    tool_input: dict[str, Any],
    state: SessionState,
    config: TurnConfig,
) -> str:
    """Placeholder tool executor that returns a stub message."""
    return f"[stub] Tool '{name}' not yet implemented."


# ── Compaction Check ──────────────────────────────────────────────────────

def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate using char heuristic."""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("content", "")))
                    total += len(str(block.get("text", "")))
    return int(total / 3.5)


def should_compact(state: SessionState, config: TurnConfig) -> bool:
    """Check if context exceeds compaction threshold."""
    return estimate_tokens(state.messages) > config.compact_threshold_tokens


# ── Core Query Loop ──────────────────────────────────────────────────────

async def run_query_loop(
    user_input: str,
    state: SessionState,
    config: TurnConfig,
    *,
    model_adapter: MockModelAdapter | None = None,
    tool_executor: ToolExecutor | None = None,
    tool_registry: ToolRegistry | None = None,
    permission_callback: PermissionCallback = _auto_permission,
    compact_handler: Callable[[SessionState, TurnConfig], str] | None = None,
) -> AsyncGenerator[Event, None]:
    """Core agent loop. Yields typed events as an async generator.

    Args:
        user_input: The user's message to process.
        state: Mutable session state carried across turns.
        config: Immutable turn configuration.
        model_adapter: Optional mock adapter (if None, uses real provider).
        tool_executor: Legacy callable to execute tools. If set, overrides registry.
        tool_registry: ToolRegistry for tool lookup and execution. Defaults to global.
        permission_callback: Returns True if tool is allowed. Default: auto for low-risk.
        compact_handler: Optional callable for compaction. Returns summary string.
    """
    reg = tool_registry or default_registry
    # Append user message
    state.messages.append(user_message(user_input))

    turn = 0
    while turn < config.max_turns:
        # ── 1. Stream model response ──────────────────────────────────
        if model_adapter is not None:
            gen = model_adapter.stream(
                config.model_name, "", state.messages,
            )
        else:
            from agent_runtime.provider import stream as provider_stream
            gen = provider_stream(
                model=config.model_name,
                system="",  # placeholder — prompt builder comes in M3
                messages=state.messages,
                tool_schemas=reg.get_schemas() if config.allow_tools else [],
                max_tokens=config.max_tokens,
            )

        assistant_text = ""
        tool_calls: list[dict[str, Any]] = []
        assistant_turn: AssistantTurn | None = None

        for chunk in gen:
            if isinstance(chunk, TextChunk):
                yield TextDeltaEvent(text=chunk.text)
                assistant_text += chunk.text
            elif isinstance(chunk, ThinkingChunk):
                yield ThinkingEvent(text=chunk.text)
            elif isinstance(chunk, AssistantTurn):
                assistant_turn = chunk
                assistant_text = chunk.text
                tool_calls = chunk.tool_calls

        if assistant_turn is None:
            # Should not happen, but guard against it
            yield FinalEvent(text=assistant_text)
            return

        # Update token counts
        state.total_input_tokens += assistant_turn.input_tokens
        state.total_output_tokens += assistant_turn.output_tokens

        # ── 2. Handle tool calls ──────────────────────────────────────
        if tool_calls and config.allow_tools:
            # Record assistant message with tool calls
            state.messages.append(assistant_message(
                content=assistant_text,
                tool_calls=tool_calls,
            ))

            for tc in tool_calls:
                yield ToolCallEvent(
                    tool_call_id=tc["id"],
                    tool_name=tc["name"],
                    tool_input=tc["input"],
                )

                # Permission check
                if not permission_callback(tc["name"], tc["input"]):
                    output = f"Permission denied for tool '{tc['name']}'."
                    yield ToolResultEvent(
                        tool_call_id=tc["id"],
                        tool_name=tc["name"],
                        output=output,
                        status="error",
                    )
                    state.messages.append(tool_result_message(
                        tool_call_id=tc["id"],
                        name=tc["name"],
                        content=output,
                    ))
                    continue

                # Execute tool via registry or legacy executor
                if tool_executor is not None:
                    try:
                        output = tool_executor(tc["name"], tc["input"], state, config)
                        status: str = "ok"
                    except Exception as e:
                        output = f"Error: {e}"
                        status = "error"
                    from agent_runtime.tools.base import LedgerEntry
                    import time as _time
                    entry = LedgerEntry(
                        tool_name=tc["name"],
                        tool_input=tc["input"],
                        status=status,
                        started_at=_time.time(),
                        ended_at=_time.time(),
                    )
                else:
                    output, entry = reg.execute(tc["name"], tc["input"])
                    status = entry.status

                state.ledger.append(entry)

                if status == "error":
                    yield RecoveryEvent(
                        reason="tool_failure",
                        detail=f"Tool '{tc['name']}' failed: {entry.error or output}",
                    )

                yield ToolResultEvent(
                    tool_call_id=tc["id"],
                    tool_name=tc["name"],
                    output=output,
                    status=status,
                )

                # Append tool result to conversation
                state.messages.append(tool_result_message(
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    content=output,
                ))

            state.turn_count += 1
            turn += 1

            # ── 3. Check compaction ───────────────────────────────────
            if should_compact(state, config):
                if compact_handler is not None:
                    summary = compact_handler(state, config)
                    state.compact_summary = summary
                yield RecoveryEvent(
                    reason="context_too_long",
                    detail="Compaction triggered.",
                )

            # Continue loop — model needs to see tool results
            continue

        # ── 4. No tool calls — model is done ──────────────────────────
        state.messages.append(assistant_message(content=assistant_text))
        state.turn_count += 1
        yield FinalEvent(text=assistant_text)
        return

    # Max turns reached
    yield FinalEvent(text=assistant_text if assistant_text else "Max turns reached.")
