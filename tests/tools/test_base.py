"""Tests for tools/base.py — ToolResult and resolve_path (REQ-08.1)."""

from __future__ import annotations

import pytest

from guild.tools.base import ToolResult, resolve_path


@pytest.mark.unit
class TestResolve:
    """resolve_path resolves relative and absolute paths correctly."""

    def test_absolute_path_returned_unchanged(self) -> None:
        """An absolute path is returned as-is regardless of working_dir."""
        result = resolve_path("/etc/hosts", "/home/user")
        assert str(result) == "/etc/hosts"

    def test_relative_path_resolved_against_working_dir(self) -> None:
        """A relative path is joined with working_dir."""
        result = resolve_path("src/main.py", "/project")
        assert str(result) == "/project/src/main.py"

    def test_relative_path_without_working_dir_resolves_to_cwd(self) -> None:
        """Without working_dir, relative path resolves against cwd."""
        result = resolve_path("file.txt", None)
        assert result.is_absolute()
        assert result.name == "file.txt"


@pytest.mark.unit
class TestToolResult:
    """ToolResult dataclass behaves correctly."""

    def test_success_str_returns_output(self) -> None:
        """str() of a successful result returns the output."""
        result = ToolResult(success=True, output="file contents here")
        assert str(result) == "file contents here"

    def test_failure_str_returns_error(self) -> None:
        """str() of a failed result returns the error."""
        result = ToolResult(success=False, output="", error="File not found")
        assert "File not found" in str(result)

    def test_default_error_is_none(self) -> None:
        """error defaults to None when not provided."""
        result = ToolResult(success=True, output="ok")
        assert result.error is None
