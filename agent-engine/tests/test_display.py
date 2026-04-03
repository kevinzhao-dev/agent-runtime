"""Tests for entrypoints/display.py — Rich-based display renderer."""

from io import StringIO

import pytest
from rich.console import Console

from engine.state import (
    CompactEvent,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from entrypoints.display import DisplayRenderer, _one_line_summary, _truncate


# ---------------------------------------------------------------------------
# Helper to build a renderer that captures output
# ---------------------------------------------------------------------------

def _make_renderer() -> tuple[DisplayRenderer, StringIO]:
    buf = StringIO()
    console = Console(file=buf, no_color=True, highlight=False, width=80)
    return DisplayRenderer(console=console), buf


def _output(buf: StringIO) -> str:
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_string(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length(self):
        assert _truncate("hello", 5) == "hello"

    def test_long_string(self):
        assert _truncate("hello world", 5) == "hello..."

    def test_empty(self):
        assert _truncate("", 10) == ""


class TestOneLineSummary:
    def test_simple_dict(self):
        result = _one_line_summary({"key": "value"})
        assert '"key": "value"' in result

    def test_truncates_long(self):
        data = {"key": "x" * 200}
        result = _one_line_summary(data, max_len=30)
        assert result.endswith("...")
        assert len(result) == 33  # 30 + "..."

    def test_non_serializable(self):
        result = _one_line_summary({"s": set()})
        assert "set()" in result


# ---------------------------------------------------------------------------
# Render method tests — verify output contains expected content
# ---------------------------------------------------------------------------

class TestRenderWelcome:
    def test_contains_version(self):
        r, buf = _make_renderer()
        r.render_welcome("v0.1.0")
        assert "v0.1.0" in _output(buf)

    def test_contains_mode_label(self):
        r, buf = _make_renderer()
        r.render_welcome("v0.1.0", " [DRY RUN]")
        assert "DRY RUN" in _output(buf)


class TestRenderGoodbye:
    def test_goodbye(self):
        r, buf = _make_renderer()
        r.render_goodbye()
        assert "Goodbye!" in _output(buf)


class TestRenderToolUse:
    def test_shows_tool_name(self):
        r, buf = _make_renderer()
        r.render_tool_use("bash", {"command": "ls"})
        out = _output(buf)
        assert "bash" in out
        assert "ls" in out

    def test_shows_input_summary(self):
        r, buf = _make_renderer()
        r.render_tool_use("read_file", {"file_path": "/tmp/test.py"})
        assert "/tmp/test.py" in _output(buf)


class TestRenderToolResult:
    def test_success_shows_content(self):
        r, buf = _make_renderer()
        r.render_tool_result("file contents here", is_error=False)
        assert "file contents here" in _output(buf)

    def test_error_shows_error(self):
        r, buf = _make_renderer()
        r.render_tool_result("not found", is_error=True)
        out = _output(buf)
        assert "Error" in out
        assert "not found" in out

    def test_long_result_collapses(self):
        long_content = "\n".join(f"line {i}" for i in range(50))
        r, buf = _make_renderer()
        r.render_tool_result(long_content, is_error=False)
        out = _output(buf)
        assert "more lines" in out
        # Should show first 5 lines
        assert "line 0" in out
        assert "line 4" in out

    def test_short_result_no_collapse(self):
        content = "\n".join(f"line {i}" for i in range(5))
        r, buf = _make_renderer()
        r.render_tool_result(content, is_error=False)
        out = _output(buf)
        assert "more lines" not in out


class TestRenderError:
    def test_shows_message(self):
        r, buf = _make_renderer()
        r.render_error("something broke")
        assert "something broke" in _output(buf)


class TestRenderCompact:
    def test_shows_token_counts(self):
        r, buf = _make_renderer()
        r.render_compact("summary", 100000, 60000)
        out = _output(buf)
        assert "100,000" in out
        assert "60,000" in out
        assert "40,000" in out


class TestRenderDone:
    def test_shows_reason_and_turns(self):
        r, buf = _make_renderer()
        r.render_done("end_turn", 3)
        out = _output(buf)
        assert "end_turn" in out
        assert "3 turns" in out

    def test_singular_turn(self):
        r, buf = _make_renderer()
        r.render_done("end_turn", 1)
        assert "1 turn" in _output(buf)


# ---------------------------------------------------------------------------
# Spinner management tests
# ---------------------------------------------------------------------------

class TestSpinnerManagement:
    def test_start_stop(self):
        r, _ = _make_renderer()
        r._start_status("Working...")
        assert r._active_status is not None
        r._stop_status()
        assert r._active_status is None

    def test_stop_when_none(self):
        r, _ = _make_renderer()
        r._stop_status()  # should not raise
        assert r._active_status is None


# ---------------------------------------------------------------------------
# render_event_stream integration tests
# ---------------------------------------------------------------------------

async def _events_from(*events):
    """Create an async iterator from a list of events."""
    for e in events:
        yield e


class TestRenderEventStream:
    @pytest.mark.asyncio
    async def test_text_only(self):
        r, buf = _make_renderer()
        done = DoneEvent(reason="end_turn", turn_count=1)
        result = await r.render_event_stream(
            _events_from(TextEvent(text="hello world"), done)
        )
        assert result is done
        out = _output(buf)
        assert "hello world" in out
        assert "end_turn" in out

    @pytest.mark.asyncio
    async def test_tool_flow(self):
        r, buf = _make_renderer()
        result = await r.render_event_stream(_events_from(
            ToolUseEvent(tool_name="bash", tool_id="t1", input={"command": "ls"}),
            ToolResultEvent(tool_id="t1", content="file.txt", is_error=False),
            TextEvent(text="Found a file."),
            DoneEvent(reason="end_turn", turn_count=2),
        ))
        out = _output(buf)
        assert "bash" in out
        assert "file.txt" in out
        assert "Found a file" in out

    @pytest.mark.asyncio
    async def test_error_event(self):
        r, buf = _make_renderer()
        await r.render_event_stream(_events_from(
            ErrorEvent(error="API failed", recoverable=True),
            DoneEvent(reason="error", turn_count=1),
        ))
        assert "API failed" in _output(buf)

    @pytest.mark.asyncio
    async def test_compact_event(self):
        r, buf = _make_renderer()
        await r.render_event_stream(_events_from(
            CompactEvent(summary="sum", tokens_before=10000, tokens_after=5000),
            TextEvent(text="continuing"),
            DoneEvent(reason="end_turn", turn_count=1),
        ))
        assert "10,000" in _output(buf)

    @pytest.mark.asyncio
    async def test_returns_none_without_done(self):
        r, _ = _make_renderer()
        result = await r.render_event_stream(_events_from(
            TextEvent(text="incomplete"),
        ))
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_on_done(self):
        r, _ = _make_renderer()
        await r.render_event_stream(_events_from(
            TextEvent(text="text"),
            DoneEvent(reason="end_turn", turn_count=1),
        ))
        # Spinner should be cleaned up
        assert r._active_status is None


class TestPermissionPrompt:
    def test_deny(self):
        buf = StringIO()
        # Simulate user typing "n\n"
        input_buf = StringIO("n\n")
        console = Console(file=buf, force_terminal=True, width=80)
        # Monkey-patch console.input to read from our buffer
        console.input = lambda prompt="": (buf.write(prompt), input_buf.readline().strip())[1]
        r = DisplayRenderer(console=console)

        result = r.render_permission_prompt("bash", {"command": "rm -rf /"})
        assert result is False
        out = _output(buf)
        assert "Permission Required" in out
        assert "bash" in out

    def test_allow(self):
        buf = StringIO()
        input_buf = StringIO("y\n")
        console = Console(file=buf, force_terminal=True, width=80)
        console.input = lambda prompt="": (buf.write(prompt), input_buf.readline().strip())[1]
        r = DisplayRenderer(console=console)

        result = r.render_permission_prompt("bash", {"command": "ls"})
        assert result is True
