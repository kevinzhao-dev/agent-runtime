"""Tests for the modular command system (commands/)."""

import json

from commands import CommandContext, CommandResult, create_default_registry
from commands.base import BaseCommand
from commands.registry import CommandRegistry
from engine.session_log import SessionLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path, messages=None):
    log = SessionLog(working_dir=str(tmp_path))
    return CommandContext(
        messages=messages or [],
        session_log=log,
        working_dir=str(tmp_path),
    ), log


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestCommandRegistry:
    def test_register_and_get(self):
        class Dummy(BaseCommand):
            name = "dummy"
            description = "A dummy"
            def execute(self, ctx, args=""): return CommandResult(output="ok")

        reg = CommandRegistry()
        reg.register(Dummy())
        assert reg.get("dummy") is not None
        assert reg.get("nonexistent") is None

    def test_execute_parses_name_and_args(self, tmp_path):
        class Echo(BaseCommand):
            name = "echo"
            description = "echo"
            def execute(self, ctx, args=""): return CommandResult(output=args, data=args)

        reg = CommandRegistry()
        reg.register(Echo())
        ctx, log = _make_ctx(tmp_path)
        result = reg.execute("/echo hello world", ctx)
        assert result is not None
        assert result.data == "hello world"
        log.close()

    def test_execute_unknown_returns_none(self, tmp_path):
        reg = CommandRegistry()
        ctx, log = _make_ctx(tmp_path)
        assert reg.execute("/nonexistent", ctx) is None
        log.close()

    def test_list_commands_hides_system_only(self):
        class Visible(BaseCommand):
            name = "visible"
            description = "v"
            def execute(self, ctx, args=""): return CommandResult()

        class Hidden(BaseCommand):
            name = "hidden"
            description = "h"
            system_only = True
            def execute(self, ctx, args=""): return CommandResult()

        reg = CommandRegistry()
        reg.register(Visible())
        reg.register(Hidden())
        assert len(reg.list_commands(include_system=False)) == 1
        assert len(reg.list_commands(include_system=True)) == 2

    def test_default_registry_has_builtins(self):
        reg = create_default_registry()
        names = [c.name for c in reg.list_commands()]
        assert "help" in names
        assert "history" in names
        assert "log" in names
        assert "compact" in names

    def test_execute_logs_to_session(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path)
        reg.execute("/help", ctx)
        log.close()
        lines = log.path.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "slash_command" in events


# ---------------------------------------------------------------------------
# Individual command tests
# ---------------------------------------------------------------------------

class TestHelpCommand:
    def test_lists_all_commands(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path)
        result = reg.execute("/help", ctx)
        assert "/help" in result.output
        assert "/history" in result.output
        assert "exit" in result.output
        # data is structured list
        assert isinstance(result.data, list)
        assert any(c["name"] == "help" for c in result.data)
        log.close()


class TestHistoryCommand:
    def test_empty(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path)
        result = reg.execute("/history", ctx)
        assert "No conversation history" in result.output
        assert result.data == []
        log.close()

    def test_with_messages(self, tmp_path):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=msgs)
        result = reg.execute("/history", ctx)
        assert "user" in result.output
        assert "hello" in result.output
        # data is the message list
        assert len(result.data) == 2
        log.close()

    def test_truncates_long_content(self, tmp_path):
        msgs = [{"role": "user", "content": "x" * 200}]
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=msgs)
        result = reg.execute("/history", ctx)
        assert "..." in result.output
        log.close()

    def test_tool_result_shown_as_placeholder(self, tmp_path):
        msgs = [{"role": "user", "content": [{"type": "tool_result", "content": "data"}]}]
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=msgs)
        result = reg.execute("/history", ctx)
        assert "[tool result]" in result.output
        log.close()


class TestLogCommand:
    def test_shows_path(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path)
        result = reg.execute("/log", ctx)
        assert "session_" in result.output
        # data is the path string
        assert isinstance(result.data, str)
        log.close()


class TestCompactCommand:
    def test_shows_stats(self, tmp_path):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=msgs)
        result = reg.execute("/compact", ctx)
        assert "Messages: 3" in result.output
        assert "User turns: 2" in result.output
        # data is structured dict
        assert result.data == {"messages": 3, "user_turns": 2}
        log.close()


# ---------------------------------------------------------------------------
# Dual-use: system programmatic access
# ---------------------------------------------------------------------------

class TestSystemUse:
    """Verify commands return structured data for programmatic callers."""

    def test_history_data_is_message_list(self, tmp_path):
        msgs = [{"role": "user", "content": "test"}]
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=msgs)
        result = reg.execute("/history", ctx)
        assert result.data == msgs
        log.close()

    def test_compact_data_is_dict(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path, messages=[])
        result = reg.execute("/compact", ctx)
        assert result.data["messages"] == 0
        assert result.data["user_turns"] == 0
        log.close()

    def test_log_data_is_path_string(self, tmp_path):
        reg = create_default_registry()
        ctx, log = _make_ctx(tmp_path)
        result = reg.execute("/log", ctx)
        assert result.data.endswith(".jsonl")
        log.close()
