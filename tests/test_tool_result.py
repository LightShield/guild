"""Tests for ToolResult structured return type (D-14 fix)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.agent import execute_tool, ToolResult


class TestToolResult:
    """D-14: Tools return structured ToolResult, not raw strings."""

    def test_tool_result_success(self):
        r = ToolResult(success=True, output="file contents here")
        assert r.success is True
        assert r.output == "file contents here"
        assert r.error is None

    def test_tool_result_failure(self):
        r = ToolResult(success=False, output="", error="file not found")
        assert r.success is False
        assert r.error == "file not found"

    def test_tool_result_str_returns_output(self):
        """str(ToolResult) should return the output for LLM consumption."""
        r = ToolResult(success=True, output="hello world")
        assert str(r) == "hello world"

    def test_tool_result_str_returns_error_on_failure(self):
        r = ToolResult(success=False, output="", error="boom")
        assert "boom" in str(r)


class TestToolExecutorsReturnToolResult:
    """All built-in tools should return ToolResult."""

    async def test_file_read_success(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        result = await execute_tool("file_read", {"path": str(f)})
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "content" in result.output

    async def test_file_read_not_found(self):
        result = await execute_tool("file_read", {"path": "/nonexistent/file"})
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error is not None

    async def test_file_write_success(self, tmp_path):
        f = tmp_path / "out.txt"
        result = await execute_tool("file_write", {"path": str(f), "content": "hello"})
        assert isinstance(result, ToolResult)
        assert result.success is True

    async def test_shell_success(self):
        result = await execute_tool("shell", {"command": "echo hello"})
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "hello" in result.output

    async def test_shell_failure(self):
        result = await execute_tool("shell", {"command": "false"})
        assert isinstance(result, ToolResult)
        assert result.success is False

    async def test_search_success(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass")
        result = await execute_tool("search", {"pattern": "foo", "path": str(tmp_path)})
        assert isinstance(result, ToolResult)
        assert result.success is True

    async def test_search_no_matches(self, tmp_path):
        (tmp_path / "a.py").write_text("nothing")
        result = await execute_tool("search", {"pattern": "zzz", "path": str(tmp_path)})
        assert isinstance(result, ToolResult)
        assert result.success is True  # no matches is not an error
        assert "No matches" in result.output

    async def test_glob_success(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        result = await execute_tool("glob", {"pattern": "*.py", "path": str(tmp_path)})
        assert isinstance(result, ToolResult)
        assert result.success is True

    async def test_unknown_tool(self):
        result = await execute_tool("nonexistent", {})
        assert isinstance(result, ToolResult)
        assert result.success is False
