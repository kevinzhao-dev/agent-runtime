"""Tests for tools/registry.py — ToolRegistry."""

from roles.config import COORDINATOR_ROLE, DEFAULT_ROLE, VERIFIER_ROLE
from tools.registry import ToolRegistry, create_default_registry


class _FakeTool:
    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return f"Fake {self._name}"

    @property
    def input_schema(self):
        return {"type": "object", "properties": {}}

    def is_read_only(self):
        return True

    def is_destructive(self):
        return False


def test_register_and_get():
    reg = ToolRegistry()
    tool = _FakeTool("my_tool")
    reg.register(tool)
    assert reg.get("my_tool") is tool


def test_get_unknown_returns_none():
    reg = ToolRegistry()
    assert reg.get("nonexistent") is None


def test_get_tools_for_role_all():
    reg = ToolRegistry()
    reg.register(_FakeTool("a"))
    reg.register(_FakeTool("b"))
    tools = reg.get_tools_for_role(DEFAULT_ROLE)  # allowed_tools=None
    assert len(tools) == 2


def test_get_tools_for_role_filtered():
    reg = ToolRegistry()
    reg.register(_FakeTool("read_file"))
    reg.register(_FakeTool("write_file"))
    reg.register(_FakeTool("bash"))
    tools = reg.get_tools_for_role(VERIFIER_ROLE)  # allowed: read_file, grep, bash
    names = {t.name for t in tools}
    assert "read_file" in names
    assert "bash" in names
    assert "write_file" not in names


def test_create_default_registry():
    reg = create_default_registry()
    names = {t.name for t in reg._tools.values()}
    assert names == {"read_file", "grep", "write_file", "edit", "bash", "agent_tool"}


def test_get_api_schemas():
    reg = create_default_registry()
    schemas = reg.get_api_schemas(COORDINATOR_ROLE)
    schema_names = {s["name"] for s in schemas}
    assert "read_file" in schema_names
    assert "agent_tool" in schema_names
    assert "write_file" not in schema_names
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s
