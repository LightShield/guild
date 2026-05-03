"""Tests for context compression — MicroCompact (REQ-07.4)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.models import Message
from guild.core.context import MicroCompact


class TestMicroCompact:
    """REQ-07.4: Local trim of old tool outputs, zero API calls."""

    def test_no_compression_under_limit(self):
        """Messages under the token limit should not be compressed."""
        msgs = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        compactor = MicroCompact(max_tokens=10000)
        result = compactor.compact(msgs)
        assert len(result) == 3
        assert result[0].content == "You are helpful."

    def test_trims_old_tool_outputs(self):
        """Old tool outputs should be truncated first."""
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="read file"),
            Message(role="assistant", content="", tool_calls=[{"id": "c0"}]),
            Message(role="tool", content="x" * 5000, tool_call_id="c0"),
            Message(role="assistant", content="I read it"),
            Message(role="user", content="now what?"),
            Message(role="assistant", content="", tool_calls=[{"id": "c1"}]),
            Message(role="tool", content="y" * 5000, tool_call_id="c1"),
            Message(role="assistant", content="done"),
        ]
        compactor = MicroCompact(max_tokens=2000)
        result = compactor.compact(msgs)
        # Old tool output (c0) should be truncated, recent (c1) preserved
        old_tool = next(m for m in result if m.tool_call_id == "c0")
        recent_tool = next(m for m in result if m.tool_call_id == "c1")
        assert len(old_tool.content) < 5000
        assert "[truncated]" in old_tool.content
        # Recent tool output should be less aggressively truncated
        assert len(recent_tool.content) >= len(old_tool.content)

    def test_preserves_system_and_recent_messages(self):
        """System prompt and last N messages should never be truncated."""
        msgs = [
            Message(role="system", content="important system prompt " * 100),
            Message(role="user", content="old question"),
            Message(role="assistant", content="old answer " * 500),
            Message(role="user", content="recent question"),
            Message(role="assistant", content="recent answer"),
        ]
        compactor = MicroCompact(max_tokens=500, preserve_recent=2)
        result = compactor.compact(msgs)
        # System prompt preserved
        assert result[0].content.startswith("important system prompt")
        # Recent messages preserved
        assert result[-1].content == "recent answer"
        assert result[-2].content == "recent question"

    def test_estimates_tokens(self):
        """Token estimation should be roughly chars/4."""
        compactor = MicroCompact(max_tokens=100)
        msgs = [Message(role="user", content="x" * 400)]
        est = compactor._estimate_tokens(msgs)
        assert est == 100  # 400 chars / 4

    def test_empty_messages(self):
        compactor = MicroCompact(max_tokens=1000)
        result = compactor.compact([])
        assert result == []

    def test_preserves_message_count(self):
        """Compaction should not remove messages, only truncate content."""
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="q1"),
            Message(role="tool", content="big " * 2000),
            Message(role="assistant", content="a1"),
        ]
        compactor = MicroCompact(max_tokens=100)
        result = compactor.compact(msgs)
        assert len(result) == len(msgs)
