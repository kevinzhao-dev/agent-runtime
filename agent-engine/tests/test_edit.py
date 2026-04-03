"""Tests for tools/edit.py."""

import pytest

from tools.base import ToolContext
from tools.edit import EditTool


@pytest.fixture
def tool():
    return EditTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(working_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_edit_replaces_unique_string(tool, ctx, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def hello():\n    return 'hello'\n")
    result = await tool.execute(
        input={"file_path": str(f), "old_string": "'hello'", "new_string": "'world'"},
        context=ctx,
    )
    assert not result.is_error
    assert f.read_text() == "def hello():\n    return 'world'\n"


@pytest.mark.asyncio
async def test_edit_not_found(tool, ctx, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("some content")
    result = await tool.execute(
        input={"file_path": str(f), "old_string": "NONEXISTENT", "new_string": "x"},
        context=ctx,
    )
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_edit_multiple_matches(tool, ctx, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("aaa\naaa\naaa\n")
    result = await tool.execute(
        input={"file_path": str(f), "old_string": "aaa", "new_string": "bbb"},
        context=ctx,
    )
    assert result.is_error
    assert "3 times" in result.content


@pytest.mark.asyncio
async def test_edit_file_not_found(tool, ctx):
    result = await tool.execute(
        input={"file_path": "/nonexistent.py", "old_string": "a", "new_string": "b"},
        context=ctx,
    )
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_edit_preserves_rest(tool, ctx, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("line1\nTARGET\nline3\n")
    await tool.execute(
        input={"file_path": str(f), "old_string": "TARGET", "new_string": "REPLACED"},
        context=ctx,
    )
    content = f.read_text()
    assert "line1" in content
    assert "REPLACED" in content
    assert "line3" in content
