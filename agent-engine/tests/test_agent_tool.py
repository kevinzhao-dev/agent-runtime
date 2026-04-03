"""Tests for tools/agent_tool.py — using DryRunClient."""

import asyncio

import pytest

from engine.dry_run import DryResponse, DryRunClient, DryToolCall
from engine.loop import ToolResult, query_loop
from engine.state import DoneEvent, TextEvent, ToolResultEvent, ToolUseEvent
from roles.config import COORDINATOR_ROLE, DEFAULT_ROLE
from tools.agent_tool import AgentTool
from tools.base import ToolContext
from tools.permission import PermissionGate, PermissionMode


@pytest.fixture
def tool():
    return AgentTool()


def test_agent_tool_properties():
    t = AgentTool()
    assert t.name == "agent_tool"
    assert t.is_read_only() is False
    assert t.is_destructive() is False
    assert "implementer" in str(t.input_schema)
    assert "verifier" in str(t.input_schema)


@pytest.mark.asyncio
async def test_unknown_role(tool, tmp_path):
    ctx = ToolContext(working_dir=str(tmp_path))
    result = await tool.execute(
        input={"task": "do something", "role": "nonexistent"}, context=ctx
    )
    assert result.is_error
    assert "Unknown role" in result.content


@pytest.mark.asyncio
async def test_coordinator_has_agent_tool():
    """Coordinator's tool list includes agent_tool."""
    from tools.registry import create_default_registry

    reg = create_default_registry()
    tools = reg.get_tools_for_role(COORDINATOR_ROLE)
    names = {t.name for t in tools}
    assert "agent_tool" in names


@pytest.mark.asyncio
async def test_implementer_no_agent_tool():
    """Implementer should NOT have agent_tool."""
    from roles.config import IMPLEMENTER_ROLE
    from tools.registry import create_default_registry

    reg = create_default_registry()
    tools = reg.get_tools_for_role(IMPLEMENTER_ROLE)
    names = {t.name for t in tools}
    assert "agent_tool" not in names
