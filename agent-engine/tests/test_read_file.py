"""Tests for tools/read_file.py."""

import pytest

from tools.base import ToolContext
from tools.read_file import ReadFileTool


@pytest.fixture
def tool():
    return ReadFileTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(working_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_read_existing_file(tool, ctx, tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")
    result = await tool.execute(input={"file_path": str(f)}, context=ctx)
    assert not result.is_error
    assert "line1" in result.content
    assert "line2" in result.content


@pytest.mark.asyncio
async def test_read_with_line_numbers(tool, ctx, tmp_path):
    f = tmp_path / "num.txt"
    f.write_text("aaa\nbbb\nccc\n")
    result = await tool.execute(input={"file_path": str(f)}, context=ctx)
    assert "1\t" in result.content
    assert "2\t" in result.content


@pytest.mark.asyncio
async def test_read_with_offset_and_limit(tool, ctx, tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("\n".join(f"line{i}" for i in range(20)))
    result = await tool.execute(
        input={"file_path": str(f), "offset": 5, "limit": 3}, context=ctx
    )
    assert "line5" in result.content
    assert "line7" in result.content
    assert "line8" not in result.content


@pytest.mark.asyncio
async def test_read_file_not_found(tool, ctx):
    result = await tool.execute(
        input={"file_path": "/nonexistent/path.txt"}, context=ctx
    )
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_read_relative_path(tool, ctx, tmp_path):
    f = tmp_path / "rel.txt"
    f.write_text("relative content")
    result = await tool.execute(input={"file_path": "rel.txt"}, context=ctx)
    assert not result.is_error
    assert "relative content" in result.content


@pytest.mark.asyncio
async def test_is_read_only(tool):
    assert tool.is_read_only() is True
    assert tool.is_destructive() is False
