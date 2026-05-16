"""Tests for tools/registry.py — central tool executor registry (REQ-08.1)."""

from __future__ import annotations

import pytest

from guild.tools.registry import build_tool_executors


@pytest.mark.unit
class TestBuildToolExecutors:
    """build_tool_executors returns the standard tool executor mapping."""

    def test_returns_dict(self) -> None:
        """The return value is a dict."""
        executors = build_tool_executors()
        assert isinstance(executors, dict)

    def test_contains_all_expected_tools(self) -> None:
        """All five standard tools are present."""
        executors = build_tool_executors()
        expected = {"file_read", "file_write", "shell", "search", "glob"}
        assert set(executors.keys()) == expected

    def test_values_are_callable(self) -> None:
        """Each executor value is a callable."""
        executors = build_tool_executors()
        for name, func in executors.items():
            assert callable(func), f"Executor for '{name}' is not callable"

    def test_file_read_executor_is_correct_function(self) -> None:
        """file_read maps to execute_file_read."""
        from guild.tools.file_ops import execute_file_read

        executors = build_tool_executors()
        assert executors["file_read"] is execute_file_read

    def test_file_write_executor_is_correct_function(self) -> None:
        """file_write maps to execute_file_write."""
        from guild.tools.file_ops import execute_file_write

        executors = build_tool_executors()
        assert executors["file_write"] is execute_file_write

    def test_shell_executor_is_correct_function(self) -> None:
        """Shell maps to execute_shell."""
        from guild.tools.shell import execute_shell

        executors = build_tool_executors()
        assert executors["shell"] is execute_shell

    def test_search_executor_is_correct_function(self) -> None:
        """Search maps to execute_search."""
        from guild.tools.search import execute_search

        executors = build_tool_executors()
        assert executors["search"] is execute_search

    def test_glob_executor_is_correct_function(self) -> None:
        """Glob maps to execute_glob."""
        from guild.tools.search import execute_glob

        executors = build_tool_executors()
        assert executors["glob"] is execute_glob


@pytest.mark.unit
class TestBuildToolExecutorsIsolation:
    """Each call returns an independent dict."""

    def test_separate_calls_return_independent_dicts(self) -> None:
        """Mutating one result does not affect the next call."""
        d1 = build_tool_executors()
        d1["extra"] = lambda: None
        d2 = build_tool_executors()
        assert "extra" not in d2

    def test_module_exports(self) -> None:
        """build_tool_executors is in the module's __all__."""
        import guild.tools.registry as mod

        assert "build_tool_executors" in mod.__all__
