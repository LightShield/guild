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
