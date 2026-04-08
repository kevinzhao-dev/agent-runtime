"""Tests for tool system: registry, ledger, individual tools, and permissions."""
import tempfile
from pathlib import Path

import pytest

from agent_runtime.tools.base import LedgerEntry, ToolRegistry, ToolSpec, registry


class TestToolSpec:
    def test_defaults(self):
        spec = ToolSpec(
            name="test", description="test tool",
            input_schema={}, executor=lambda p: "ok",
        )
        assert spec.risk == "low"
        assert spec.side_effecting is False


class TestToolRegistry:
    def setup_method(self):
        self.reg = ToolRegistry()
        self.reg.register(ToolSpec(
            name="echo",
            description="Echoes input",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            executor=lambda p: p.get("text", ""),
        ))

    def test_register_and_get(self):
        assert self.reg.get("echo") is not None
        assert self.reg.get("nonexistent") is None

    def test_list_names(self):
        assert "echo" in self.reg.list_names()

    def test_get_schemas(self):
        schemas = self.reg.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "echo"

    def test_execute_success(self):
        output, entry = self.reg.execute("echo", {"text": "hello"})
        assert output == "hello"
        assert entry.status == "ok"
        assert entry.started_at > 0
        assert entry.ended_at is not None
        assert entry.ended_at >= entry.started_at

    def test_execute_unknown_tool(self):
        output, entry = self.reg.execute("unknown", {})
        assert "Unknown tool" in output
        assert entry.status == "error"

    def test_execute_error(self):
        self.reg.register(ToolSpec(
            name="fail",
            description="Always fails",
            input_schema={},
            executor=lambda p: (_ for _ in ()).throw(ValueError("boom")),
        ))
        output, entry = self.reg.execute("fail", {})
        assert entry.status == "error"
        assert "boom" in entry.error

    def test_output_truncation(self):
        self.reg.register(ToolSpec(
            name="big",
            description="Returns large output",
            input_schema={},
            executor=lambda p: "x" * 100_000,
        ))
        output, entry = self.reg.execute("big", {}, max_output=1000)
        assert len(output) < 100_000
        assert "truncated" in output

    def test_is_high_risk(self):
        self.reg.register(ToolSpec(
            name="danger",
            description="Dangerous",
            input_schema={},
            executor=lambda p: "ok",
            risk="high",
        ))
        assert self.reg.is_high_risk("danger") is True
        assert self.reg.is_high_risk("echo") is False
        assert self.reg.is_high_risk("nonexistent") is False


class TestLedgerEntry:
    def test_defaults(self):
        entry = LedgerEntry(tool_name="bash", tool_input={"cmd": "ls"})
        assert entry.status == "ok"
        assert entry.error == ""


class TestGlobalRegistry:
    """Test that the global registry has all 5 tools registered."""

    def test_all_tools_registered(self):
        names = registry.list_names()
        assert "read_file" in names
        assert "write_file" in names
        assert "bash" in names
        assert "grep_search" in names
        assert "ask_user" in names

    def test_bash_is_high_risk(self):
        assert registry.is_high_risk("bash") is True

    def test_read_file_is_low_risk(self):
        assert registry.is_high_risk("read_file") is False

    def test_schemas_have_required_fields(self):
        for schema in registry.get_schemas():
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema


class TestReadFileTool:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        output, entry = registry.execute("read_file", {"file_path": str(f)})
        assert entry.status == "ok"
        assert "line1" in output
        assert "1\t" in output  # line numbers

    def test_read_nonexistent_file(self):
        output, entry = registry.execute("read_file", {"file_path": "/nonexistent/file.txt"})
        assert "Error" in output

    def test_read_with_offset_and_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        output, entry = registry.execute("read_file", {
            "file_path": str(f), "offset": 1, "limit": 2,
        })
        assert "2\tb" in output
        assert "3\tc" in output
        assert "a" not in output


class TestWriteFileTool:
    def test_write_new_file(self, tmp_path):
        f = tmp_path / "out.txt"
        output, entry = registry.execute("write_file", {
            "file_path": str(f), "content": "hello",
        })
        assert entry.status == "ok"
        assert f.read_text() == "hello"

    def test_write_creates_dirs(self, tmp_path):
        f = tmp_path / "sub" / "deep" / "file.txt"
        registry.execute("write_file", {"file_path": str(f), "content": "data"})
        assert f.read_text() == "data"


class TestBashTool:
    def test_simple_command(self):
        output, entry = registry.execute("bash", {"command": "echo hello"})
        assert entry.status == "ok"
        assert "hello" in output

    def test_command_with_exit_code(self):
        output, entry = registry.execute("bash", {"command": "exit 1"})
        assert "exit code: 1" in output

    def test_timeout(self):
        output, entry = registry.execute("bash", {"command": "sleep 10", "timeout": 1})
        assert "timed out" in output


class TestGrepSearchTool:
    def test_search_file(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\ndef world():\n    pass\n")
        output, entry = registry.execute("grep_search", {
            "pattern": "def \\w+",
            "path": str(tmp_path),
        })
        assert entry.status == "ok"
        assert "hello" in output
        assert "world" in output

    def test_no_matches(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("nothing here")
        output, entry = registry.execute("grep_search", {
            "pattern": "xyz123",
            "path": str(tmp_path),
        })
        assert "No matches" in output

    def test_invalid_regex(self):
        output, entry = registry.execute("grep_search", {"pattern": "[invalid"})
        assert "Invalid regex" in output


class TestAskUserTool:
    def test_raises_user_input_required(self):
        from agent_runtime.tools.ask_user import UserInputRequired
        with pytest.raises(UserInputRequired) as exc_info:
            spec = registry.get("ask_user")
            spec.executor({"question": "What next?"})
        assert exc_info.value.question == "What next?"
