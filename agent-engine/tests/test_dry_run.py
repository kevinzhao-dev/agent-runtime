"""Tests for engine/dry_run.py — DryRunClient mock."""

import pytest

from engine.dry_run import DryResponse, DryRunClient, DryToolCall


def test_dry_response_auto_stop_reason_end_turn():
    r = DryResponse(text="hello")
    assert r.stop_reason == "end_turn"


def test_dry_response_auto_stop_reason_tool_use():
    r = DryResponse(tool_calls=[DryToolCall(name="read_file", input={})])
    assert r.stop_reason == "tool_use"


def test_dry_tool_call_auto_id():
    tc = DryToolCall(name="bash", input={"command": "ls"})
    assert tc.id.startswith("toolu_dry_")


@pytest.mark.asyncio
async def test_dry_run_client_stream():
    client = DryRunClient(responses=[DryResponse(text="hello world")])
    async with client.messages.stream(messages=[]) as stream:
        chunks = []
        async for event in stream:
            chunks.append(event.delta.text)
        msg = await stream.get_final_message()

    assert "".join(chunks) == "hello world"
    assert msg.stop_reason == "end_turn"
    assert msg.usage.input_tokens == 100


@pytest.mark.asyncio
async def test_dry_run_client_tool_use():
    client = DryRunClient(responses=[
        DryResponse(text="ok", tool_calls=[
            DryToolCall(name="read_file", input={"file_path": "a.py"}),
        ]),
    ])
    async with client.messages.stream(messages=[]) as stream:
        async for _ in stream:
            pass
        msg = await stream.get_final_message()

    assert len(msg.content) == 2  # text + tool_use
    assert msg.content[0].type == "text"
    assert msg.content[1].type == "tool_use"
    assert msg.content[1].name == "read_file"


@pytest.mark.asyncio
async def test_dry_run_client_echo_fallback():
    client = DryRunClient(responses=[])  # no scripted responses
    async with client.messages.stream(
        messages=[{"role": "user", "content": "test input"}]
    ) as stream:
        async for _ in stream:
            pass
        msg = await stream.get_final_message()

    assert "DRY RUN echo" in msg.content[0].text
    assert "test input" in msg.content[0].text


@pytest.mark.asyncio
async def test_dry_run_client_create():
    """Test the non-streaming create() method used by compact."""
    client = DryRunClient(responses=[DryResponse(text="summary")])
    msg = await client.messages.create(messages=[{"role": "user", "content": "hi"}])
    assert msg.content[0].text == "summary"
