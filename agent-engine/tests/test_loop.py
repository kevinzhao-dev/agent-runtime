"""Tests for the query loop using DryRunClient.

These tests verify the core loop workflow, state transitions,
and event flow without making real API calls.
"""

from __future__ import annotations

import asyncio

import pytest

from engine.dry_run import DryResponse, DryRunClient, DryToolCall
from engine.loop import ToolResult, query_loop
from engine.state import (
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from roles.config import DEFAULT_ROLE
from tools.registry import create_default_registry


async def _collect_events(async_gen) -> list:
    """Helper to collect all events from an async generator."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


def _make_schemas():
    registry = create_default_registry()
    return registry.get_api_schemas(DEFAULT_ROLE)


async def _mock_executor(name: str, tid: str, inp: dict) -> ToolResult:
    """Simple mock executor that returns tool name as content."""
    return ToolResult(content=f"executed {name}")


# ---------------------------------------------------------------------------
# Basic conversation (no tools)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_basic_conversation():
    """Model responds with text, no tool use -> end_turn."""
    client = DryRunClient(responses=[
        DryResponse(text="Hello! I can help with that."),
    ])

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "hi"}],
        role_config=DEFAULT_ROLE,
        client=client,
    ))

    text_events = [e for e in events if isinstance(e, TextEvent)]
    done_events = [e for e in events if isinstance(e, DoneEvent)]

    assert len(text_events) > 0
    full_text = "".join(e.text for e in text_events)
    assert "Hello" in full_text

    assert len(done_events) == 1
    assert done_events[0].reason == "end_turn"
    assert done_events[0].turn_count == 1


# ---------------------------------------------------------------------------
# Tool use flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_use_flow():
    """Model requests a tool, gets result, then responds."""
    client = DryRunClient(responses=[
        DryResponse(
            text="Reading the file.",
            tool_calls=[DryToolCall(name="read_file", input={"file_path": "test.py"})],
        ),
        DryResponse(text="The file looks good."),
    ])

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "check test.py"}],
        role_config=DEFAULT_ROLE,
        tools=_make_schemas(),
        tool_executor=_mock_executor,
        client=client,
    ))

    # Should have: TextEvents, ToolUseEvent, ToolResultEvent, more TextEvents, DoneEvent
    tool_use = [e for e in events if isinstance(e, ToolUseEvent)]
    tool_result = [e for e in events if isinstance(e, ToolResultEvent)]
    done = [e for e in events if isinstance(e, DoneEvent)]

    assert len(tool_use) == 1
    assert tool_use[0].tool_name == "read_file"

    assert len(tool_result) == 1
    assert "executed read_file" in tool_result[0].content

    assert len(done) == 1
    assert done[0].reason == "end_turn"
    assert done[0].turn_count == 2  # 2 model calls


# ---------------------------------------------------------------------------
# Max turns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_turns():
    """Loop stops when max_turns is reached."""
    # Every response requests a tool, so the loop keeps going
    client = DryRunClient(responses=[
        DryResponse(
            text="step",
            tool_calls=[DryToolCall(name="read_file", input={"file_path": "a.py"})],
        ),
    ] * 5)  # 5 scripted responses, but max_turns=2

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "do stuff"}],
        role_config=DEFAULT_ROLE,
        tools=_make_schemas(),
        tool_executor=_mock_executor,
        max_turns=2,
        client=client,
    ))

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].reason == "max_turns"
    assert done[0].turn_count == 2


# ---------------------------------------------------------------------------
# Abort signal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_abort_signal():
    """Loop exits immediately when abort signal is set."""
    abort = asyncio.Event()
    abort.set()  # Pre-set before loop starts

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "hi"}],
        role_config=DEFAULT_ROLE,
        abort_signal=abort,
        client=DryRunClient(),
    ))

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].reason == "abort"


# ---------------------------------------------------------------------------
# DoneEvent carries messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_done_event_carries_messages():
    """DoneEvent includes the final conversation messages."""
    client = DryRunClient(responses=[
        DryResponse(text="answer"),
    ])

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "question"}],
        role_config=DEFAULT_ROLE,
        client=client,
    ))

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    messages = done[0].messages
    # Should have: original user message + assistant response
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Multiple tool calls in one response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_tool_calls():
    """Model requests multiple tools in a single response."""
    client = DryRunClient(responses=[
        DryResponse(
            text="Let me check both files.",
            tool_calls=[
                DryToolCall(name="read_file", input={"file_path": "a.py"}),
                DryToolCall(name="read_file", input={"file_path": "b.py"}),
            ],
        ),
        DryResponse(text="Both files look correct."),
    ])

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "check a.py and b.py"}],
        role_config=DEFAULT_ROLE,
        tools=_make_schemas(),
        tool_executor=_mock_executor,
        client=client,
    ))

    tool_uses = [e for e in events if isinstance(e, ToolUseEvent)]
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]

    assert len(tool_uses) == 2
    assert len(tool_results) == 2


# ---------------------------------------------------------------------------
# Echo fallback when responses exhausted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_echo_fallback():
    """When scripted responses are exhausted, DryRunClient echoes input."""
    client = DryRunClient(responses=[])  # No scripted responses

    events = await _collect_events(query_loop(
        messages=[{"role": "user", "content": "tell me a joke"}],
        role_config=DEFAULT_ROLE,
        client=client,
    ))

    text = "".join(e.text for e in events if isinstance(e, TextEvent))
    assert "DRY RUN echo" in text
    assert "tell me a joke" in text
