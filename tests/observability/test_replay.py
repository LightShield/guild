"""Tests for observability/replay.py — session replay (REQ-11.2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.observability.replay import SessionReplay
from guild.storage.sqlite import Storage


@pytest.mark.unit
@pytest.mark.req("REQ-11.2")
class TestSessionReplay:
    """Tests for session replay from stored messages."""

    async def test_get_session_returns_messages(self, tmp_path: Path) -> None:
        """get_session returns all messages for an agent in order."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            await storage.append_message("agent-1", "system", "You are helpful.")
            await storage.append_message("agent-1", "user", "Fix the bug.")
            await storage.append_message("agent-1", "assistant", "On it.")

            replay = SessionReplay(storage)
            messages = await replay.get_session("agent-1")

            assert len(messages) == 3
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[2]["role"] == "assistant"
            assert messages[0]["content"] == "You are helpful."
            assert messages[1]["content"] == "Fix the bug."
            assert messages[2]["content"] == "On it."
        finally:
            await storage.close()

    async def test_get_session_returns_empty_for_unknown_agent(self, tmp_path: Path) -> None:
        """get_session returns empty list for non-existent agent."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            replay = SessionReplay(storage)
            messages = await replay.get_session("nonexistent")

            assert messages == []
        finally:
            await storage.close()

    async def test_session_summary_counts_turns(self, tmp_path: Path) -> None:
        """get_session_summary correctly counts turns and tool calls."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            tool_calls_json = json.dumps(
                [{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}]
            )
            await storage.append_message("agent-1", "system", "You help.")
            await storage.append_message("agent-1", "user", "Do task.")
            await storage.append_message(
                "agent-1",
                "assistant",
                "",
                tool_calls=tool_calls_json,
            )
            await storage.append_message("agent-1", "tool", "file contents")
            await storage.append_message("agent-1", "assistant", "Done.")

            replay = SessionReplay(storage)
            summary = await replay.get_session_summary("agent-1")

            assert summary["turn_count"] == 2  # 2 assistant messages
            assert summary["tool_calls"] == 1  # 1 tool message
            assert "file_read" in summary["tools_used"]
            assert summary["message_count"] == 5
        finally:
            await storage.close()

    async def test_session_summary_empty_for_no_messages(self, tmp_path: Path) -> None:
        """get_session_summary returns zeroes for agent with no messages."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            replay = SessionReplay(storage)
            summary = await replay.get_session_summary("empty-agent")

            assert summary["turn_count"] == 0
            assert summary["tool_calls"] == 0
            assert summary["tools_used"] == []
            assert summary["message_count"] == 0
        finally:
            await storage.close()

    async def test_format_for_display_readable(self, tmp_path: Path) -> None:
        """format_for_display produces human-readable output."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            await storage.append_message("agent-1", "user", "Hello")
            await storage.append_message("agent-1", "assistant", "Hi there!")

            replay = SessionReplay(storage)
            messages = await replay.get_session("agent-1")
            output = replay.format_for_display(messages)

            assert "[USER] Hello" in output
            assert "[ASSISTANT] Hi there!" in output
            assert "---" in output
        finally:
            await storage.close()

    def test_format_for_display_empty_session(self) -> None:
        """format_for_display returns placeholder for empty messages."""
        # Create a mock-like storage (won't be used)
        from unittest.mock import MagicMock

        replay = SessionReplay(MagicMock())
        output = replay.format_for_display([])

        assert output == "(empty session)"


# ======================================================================
# Session replay edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-11.2")
class TestReplayEdgeCases:
    """Cover session replay edge cases."""

    async def test_replay_empty_session(self, tmp_path: Path) -> None:
        """Replaying a session with no messages returns empty."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        replay = SessionReplay(store)
        messages = await replay.get_session("nonexistent-agent")
        assert messages == []
        await store.close()

    async def test_get_session_summary_empty(self, tmp_path: Path) -> None:
        """Summarizing a session with no messages returns zero counts."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        replay = SessionReplay(store)
        summary = await replay.get_session_summary("nonexistent-agent")
        assert summary["turn_count"] == 0
        assert summary["message_count"] == 0
        await store.close()

    def test_format_for_display_empty(self) -> None:
        """format_for_display returns placeholder for empty session."""
        from unittest.mock import MagicMock

        replay = SessionReplay(MagicMock())
        result = replay.format_for_display([])
        assert "empty" in result.lower()

    def test_extract_tool_names_invalid_json(self) -> None:
        """_extract_tool_names handles invalid JSON gracefully."""
        tools: list[str] = []
        SessionReplay._extract_tool_names("not-json", tools)
        assert tools == []

    def test_extract_tool_names_valid(self) -> None:
        """_extract_tool_names extracts tool names from valid JSON."""
        import json

        tools: list[str] = []
        calls = json.dumps(
            [
                {"function": {"name": "shell"}},
                {"function": {"name": "file_read"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        assert "shell" in tools
        assert "file_read" in tools


# ======================================================================
# Replay extract tool names branches (from coverage gaps)
# ======================================================================


@pytest.mark.req("REQ-11.2")
@pytest.mark.unit
class TestReplayExtractToolNamesBranches:
    """Cover the branch exits in _extract_tool_names."""

    def test_extract_tool_names_non_list_json(self) -> None:
        """When JSON parses to a non-list, branch exits early (line 98->exit)."""
        tools: list[str] = []
        # Valid JSON but not a list -- should hit `if isinstance(calls, list)` False branch
        SessionReplay._extract_tool_names('{"not": "a list"}', tools)
        assert tools == []

    def test_extract_tool_names_call_without_name(self) -> None:
        """When a call has no function name, it\'s skipped (line 102->99)."""
        import json

        tools: list[str] = []
        # A call with empty name -- `if name` is False, branch 102->99
        calls = json.dumps(
            [
                {"function": {"name": ""}},
                {"function": {"name": "valid_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        # Only valid_tool should be extracted
        assert tools == ["valid_tool"]

    def test_extract_tool_names_call_missing_function_key(self) -> None:
        """When a call has no \'function\' key, it\'s handled."""
        import json

        tools: list[str] = []
        calls = json.dumps(
            [
                {"other_key": "value"},
                {"function": {"name": "good_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        assert tools == ["good_tool"]

    def test_extract_tool_names_deduplication(self) -> None:
        """Duplicate tool names are not added twice (name not in tools_used branch)."""
        import json

        tools: list[str] = ["existing_tool"]
        calls = json.dumps(
            [
                {"function": {"name": "existing_tool"}},
                {"function": {"name": "new_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        # existing_tool should NOT be duplicated
        assert tools.count("existing_tool") == 1
        assert "new_tool" in tools
