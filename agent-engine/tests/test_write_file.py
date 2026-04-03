"""Tests for tools/write_file.py."""

import pytest

from tools.base import ToolContext
from tools.write_file import WriteFileTool


@pytest.fixture
def tool():
    return WriteFileTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(working_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_write_new_file(tool, ctx, tmp_path):
    path = str(tmp_path / "new.txt")
    result = await tool.execute(
        input={"file_path": path, "content": "hello world"}, context=ctx
    )
    assert not result.is_error
    assert (tmp_path / "new.txt").read_text() == "hello world"


@pytest.mark.asyncio
async def test_write_creates_directories(tool, ctx, tmp_path):
    path = str(tmp_path / "sub" / "dir" / "deep.txt")
    result = await tool.execute(
        input={"file_path": path, "content": "deep"}, context=ctx
    )
    assert not result.is_error
    assert (tmp_path / "sub" / "dir" / "deep.txt").read_text() == "deep"


@pytest.mark.asyncio
async def test_write_overwrites_existing(tool, ctx, tmp_path):
    f = tmp_path / "exist.txt"
    f.write_text("old content")
    result = await tool.execute(
        input={"file_path": str(f), "content": "new content"}, context=ctx
    )
    assert not result.is_error
    assert f.read_text() == "new content"


@pytest.mark.asyncio
async def test_write_relative_path(tool, ctx, tmp_path):
    result = await tool.execute(
        input={"file_path": "relative.txt", "content": "data"}, context=ctx
    )
    assert not result.is_error
    assert (tmp_path / "relative.txt").read_text() == "data"


@pytest.mark.asyncio
async def test_is_destructive(tool):
    assert tool.is_read_only() is False
    assert tool.is_destructive() is True
