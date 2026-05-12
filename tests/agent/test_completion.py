"""Tests for agent/completion.py — completion heuristics (Fixes A, B, C)."""

from __future__ import annotations

import pytest

from guild.agent.completion import (
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.tools.base import ToolResult


@pytest.mark.unit
class TestDeduplication:
    """Fix C: Detect and prevent repeated identical tool calls."""

    def test_dedup_detects_identical_consecutive_calls(self) -> None:
        """Two calls with same function name and args are duplicates."""
        call = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "a.txt", "content": "x"},
            }
        }
        recent = [
            {
                "function": {
                    "name": "file_write",
                    "arguments": {"path": "a.txt", "content": "x"},
                }
            }
        ]
        assert is_duplicate_call(call, recent) is True

    def test_dedup_allows_different_calls(self) -> None:
        """Two calls with different function names are not duplicates."""
        call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        recent = [
            {
                "function": {
                    "name": "file_write",
                    "arguments": {"path": "a.txt", "content": "x"},
                }
            }
        ]
        assert is_duplicate_call(call, recent) is False

    def test_dedup_allows_same_tool_different_args(self) -> None:
        """Same tool with different arguments is not a duplicate."""
        call = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "b.txt", "content": "y"},
            }
        }
        recent = [
            {
                "function": {
                    "name": "file_write",
                    "arguments": {"path": "a.txt", "content": "x"},
                }
            }
        ]
        assert is_duplicate_call(call, recent) is False


@pytest.mark.unit
class TestCompletionNudge:
    """Fix B: Nudge model to finish after successful simple actions."""

    def test_completion_nudge_fires_after_single_successful_action(self) -> None:
        """A single successful tool result triggers the nudge."""
        results = [ToolResult(success=True, output="Wrote 10 chars to /tmp/a.txt")]
        assert should_nudge_completion(results) is True

    def test_completion_nudge_does_not_fire_after_failure(self) -> None:
        """Failed tool results do not trigger nudge."""
        results = [ToolResult(success=False, output="", error="File not found")]
        assert should_nudge_completion(results) is False

    def test_completion_nudge_does_not_fire_after_multiple_actions(self) -> None:
        """Multiple tool results suggest a complex task — no nudge."""
        results = [
            ToolResult(success=True, output="Read file"),
            ToolResult(success=True, output="Wrote file"),
            ToolResult(success=True, output="Read another"),
        ]
        assert should_nudge_completion(results) is False


@pytest.mark.unit
class TestFormatToolResult:
    """Fix A: Enriched tool result messages include closure signal on success."""

    def test_format_tool_result_success_includes_closure_signal(self) -> None:
        """Successful results include the hint to provide final response."""
        result = ToolResult(success=True, output="Wrote 10 chars to /tmp/a.txt")
        formatted = format_tool_result("file_write", result)
        assert "Wrote 10 chars" in formatted
        assert "final response" in formatted.lower() or "task" in formatted.lower()

    def test_format_tool_result_error_has_no_closure_signal(self) -> None:
        """Error results do NOT include the closure hint."""
        result = ToolResult(success=False, output="", error="File not found: /bad")
        formatted = format_tool_result("file_read", result)
        assert "File not found" in formatted
        # Should not have the closure nudge
        assert "final response" not in formatted.lower()
        assert "completes your task" not in formatted.lower()

    def test_format_tool_result_includes_tool_name(self) -> None:
        """Formatted result includes the tool name for context."""
        result = ToolResult(success=True, output="content")
        formatted = format_tool_result("file_read", result)
        assert "file_read" in formatted

    def test_format_tool_result_error_includes_tool_name(self) -> None:
        """Error formatted result also includes the tool name."""
        result = ToolResult(success=False, output="", error="denied")
        formatted = format_tool_result("file_write", result)
        assert "file_write" in formatted


@pytest.mark.unit
class TestDeduplicationEdgeCases:
    """Edge cases for the deduplication logic."""

    def test_dedup_with_empty_recent_calls(self) -> None:
        """No recent calls means nothing is a duplicate."""
        call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        assert is_duplicate_call(call, []) is False

    def test_dedup_with_missing_function_key(self) -> None:
        """Malformed call without 'function' key does not crash."""
        call = {"something_else": "bad"}
        recent = [{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}]
        # Should not raise — just returns False
        assert is_duplicate_call(call, recent) is False

    def test_dedup_with_nested_arguments(self) -> None:
        """Complex nested arguments are compared correctly."""
        call = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "a.txt", "content": "line1\nline2"},
            }
        }
        same = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "a.txt", "content": "line1\nline2"},
            }
        }
        different = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "a.txt", "content": "line1\nline3"},
            }
        }
        assert is_duplicate_call(call, [same]) is True
        assert is_duplicate_call(call, [different]) is False


@pytest.mark.unit
class TestCompletionNudgeEdgeCases:
    """Edge cases for should_nudge_completion."""

    def test_nudge_with_empty_results_list(self) -> None:
        """Empty results list does not trigger nudge."""
        assert should_nudge_completion([]) is False

    def test_nudge_with_exactly_two_successful_results(self) -> None:
        """Two results is at/above threshold — no nudge."""
        results = [
            ToolResult(success=True, output="a"),
            ToolResult(success=True, output="b"),
        ]
        assert should_nudge_completion(results) is False

    def test_nudge_with_mixed_success_and_failure(self) -> None:
        """If any result failed, no nudge (even if just one result)."""
        results = [ToolResult(success=False, output="", error="oops")]
        assert should_nudge_completion(results) is False
