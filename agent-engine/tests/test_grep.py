"""Tests for tools/grep.py."""

import pytest

from tools.base import ToolContext
from tools.grep import GrepTool


@pytest.fixture
def tool():
    return GrepTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(working_dir=str(tmp_path))


@pytest.fixture
def sample_files(tmp_path):
    (tmp_path / "hello.py").write_text("def hello():\n    return 'hello world'\n")
    (tmp_path / "main.py").write_text("from hello import hello\nhello()\n")
    (tmp_path / "data.txt").write_text("no python here\njust data\n")
    return tmp_path


@pytest.mark.asyncio
async def test_grep_basic(tool, ctx, sample_files):
    result = await tool.execute(input={"pattern": "hello"}, context=ctx)
    assert not result.is_error
    assert "hello.py" in result.content
    assert "main.py" in result.content


@pytest.mark.asyncio
async def test_grep_regex(tool, ctx, sample_files):
    result = await tool.execute(input={"pattern": "def \\w+"}, context=ctx)
    assert not result.is_error
    assert "hello.py" in result.content
    assert "def hello" in result.content


@pytest.mark.asyncio
async def test_grep_glob_filter(tool, ctx, sample_files):
    result = await tool.execute(
        input={"pattern": "hello", "glob": "*.py"}, context=ctx
    )
    assert not result.is_error
    assert "hello.py" in result.content
    # data.txt should not appear (filtered by glob)


@pytest.mark.asyncio
async def test_grep_case_insensitive(tool, ctx, tmp_path):
    (tmp_path / "test.txt").write_text("Hello World\nhello world\nHELLO WORLD\n")
    result = await tool.execute(
        input={"pattern": "hello", "case_insensitive": True}, context=ctx
    )
    assert not result.is_error
    # Should find all 3 lines
    assert result.content.count("test.txt") == 3


@pytest.mark.asyncio
async def test_grep_no_matches(tool, ctx, sample_files):
    result = await tool.execute(input={"pattern": "ZZZZNOTFOUND"}, context=ctx)
    assert "no matches" in result.content.lower()


@pytest.mark.asyncio
async def test_grep_invalid_regex(tool, ctx, sample_files):
    result = await tool.execute(input={"pattern": "[invalid"}, context=ctx)
    assert result.is_error
    assert "invalid" in result.content.lower()


@pytest.mark.asyncio
async def test_grep_single_file(tool, ctx, sample_files):
    result = await tool.execute(
        input={"pattern": "hello", "path": str(sample_files / "hello.py")},
        context=ctx,
    )
    assert not result.is_error
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_grep_path_not_found(tool, ctx):
    result = await tool.execute(
        input={"pattern": "x", "path": "/nonexistent/dir"}, context=ctx
    )
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_is_read_only(tool):
    assert tool.is_read_only() is True
    assert tool.is_destructive() is False
