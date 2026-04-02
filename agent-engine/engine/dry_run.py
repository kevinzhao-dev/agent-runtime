"""Dry-run client — simulates Anthropic API without real calls.

Provides a DryRunClient that mimics the anthropic.AsyncAnthropic interface,
returning scripted or echo responses. Useful for:
  - Understanding the loop workflow without API costs
  - Testing state transitions and tool execution
  - Debugging event flow

Usage:
    from engine.dry_run import DryRunClient
    client = DryRunClient()
    async for event in query_loop(messages=[...], client=client):
        ...

    # Or with scripted tool-use responses:
    client = DryRunClient(responses=[
        DryResponse(text="Let me read that file.", tool_calls=[
            DryToolCall(name="read_file", input={"file_path": "hello.py"}),
        ]),
        DryResponse(text="The file contains a hello world program."),
    ])
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DryToolCall:
    """A scripted tool call for the model to request."""
    name: str
    input: dict[str, Any]
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"toolu_dry_{uuid.uuid4().hex[:12]}"


@dataclass
class DryResponse:
    """A scripted response from the model."""
    text: str = ""
    tool_calls: list[DryToolCall] = field(default_factory=list)
    stop_reason: str = ""  # auto-determined if empty
    input_tokens: int = 100
    output_tokens: int = 50

    def __post_init__(self):
        if not self.stop_reason:
            self.stop_reason = "tool_use" if self.tool_calls else "end_turn"


# ---------------------------------------------------------------------------
# Fake SDK objects that mimic the anthropic SDK's response types
# ---------------------------------------------------------------------------

class _FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, tc: DryToolCall):
        self.type = "tool_use"
        self.id = tc.id
        self.name = tc.name
        self.input = tc.input


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessage:
    def __init__(self, resp: DryResponse):
        self.content = []
        if resp.text:
            self.content.append(_FakeTextBlock(resp.text))
        for tc in resp.tool_calls:
            self.content.append(_FakeToolUseBlock(tc))
        self.stop_reason = resp.stop_reason
        self.usage = _FakeUsage(resp.input_tokens, resp.output_tokens)


class _FakeStreamDelta:
    def __init__(self, text: str):
        self.type = "text_delta"
        self.text = text


class _FakeStreamEvent:
    def __init__(self, text: str):
        self.type = "content_block_delta"
        self.delta = _FakeStreamDelta(text)


class _FakeStream:
    """Mimics the async context manager from client.messages.stream()."""

    def __init__(self, response: DryResponse):
        self._response = response
        self._message = _FakeMessage(response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._stream_events()

    async def _stream_events(self):
        """Yield text as streaming events, word by word for visibility."""
        if self._response.text:
            words = self._response.text.split(" ")
            for i, word in enumerate(words):
                chunk = word if i == 0 else " " + word
                yield _FakeStreamEvent(chunk)

    async def get_final_message(self):
        return self._message


class _FakeMessages:
    """Mimics client.messages with stream() and create() methods."""

    def __init__(self, responses: list[DryResponse]):
        self._responses = responses
        self._call_count = 0

    def _next_response(self, messages: list[dict]) -> DryResponse:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        # Default: echo back the last user message
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_user = content
                elif isinstance(content, list):
                    # tool_result or structured content
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            parts.append(block.get("content", str(block)))
                    last_user = "; ".join(parts)
                break
        self._call_count += 1
        return DryResponse(
            text=f"[DRY RUN echo] Received: {last_user[:200]}",
        )

    def stream(self, **kwargs) -> _FakeStream:
        messages = kwargs.get("messages", [])
        resp = self._next_response(messages)
        return _FakeStream(resp)

    async def create(self, **kwargs) -> _FakeMessage:
        messages = kwargs.get("messages", [])
        resp = self._next_response(messages)
        return _FakeMessage(resp)


class DryRunClient:
    """Drop-in replacement for anthropic.AsyncAnthropic.

    Args:
        responses: Scripted responses in order. After exhausted, echoes input.

    Example:
        client = DryRunClient(responses=[
            DryResponse(text="I'll create that file.", tool_calls=[
                DryToolCall(name="write_file", input={
                    "file_path": "hello.py",
                    "content": "print('hello')",
                }),
            ]),
            DryResponse(text="Done! I created hello.py."),
        ])
    """

    def __init__(self, responses: list[DryResponse] | None = None):
        self.messages = _FakeMessages(responses or [])
