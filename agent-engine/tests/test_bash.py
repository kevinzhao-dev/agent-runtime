"""Tests for tools/bash.py."""

import pytest

from tools.base import ToolContext
from tools.bash import BashTool


@pytest.fixture
def tool():
    return BashTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(working_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_echo(tool, ctx):
    result = await tool.execute(input={"command": "echo hello"}, context=ctx)
    assert not result.is_error
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_exit_code_nonzero(tool, ctx):
    result = await tool.execute(input={"command": "exit 1"}, context=ctx)
    assert result.is_error
    assert "Exit code 1" in result.content


@pytest.mark.asyncio
async def test_stderr_captured(tool, ctx):
    result = await tool.execute(
        input={"command": "echo err >&2"}, context=ctx
    )
    assert "err" in result.content


@pytest.mark.asyncio
async def test_timeout(tool, ctx):
    result = await tool.execute(
        input={"command": "sleep 10", "timeout": 1}, context=ctx
    )
    assert result.is_error
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_working_dir(tool, tmp_path):
    (tmp_path / "marker.txt").write_text("found")
    ctx = ToolContext(working_dir=str(tmp_path))
    result = await tool.execute(input={"command": "cat marker.txt"}, context=ctx)
    assert not result.is_error
    assert "found" in result.content


@pytest.mark.asyncio
async def test_is_destructive(tool):
    assert tool.is_read_only() is False
    assert tool.is_destructive() is True
