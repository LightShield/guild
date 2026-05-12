"""Tests for agent/message.py — Message dataclass serialization (REQ-06.1)."""

from __future__ import annotations

import pytest

from guild.agent.message import Message


@pytest.mark.unit
class TestMessageAttributes:
    """Message dataclass stores conversation data correctly."""

    def test_required_fields(self) -> None:
        """A Message can be created with just role and content."""
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_optional_fields_default_to_none(self) -> None:
        """tool_calls and tool_call_id default to None."""
        msg = Message(role="assistant", content="hi")
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_tool_calls_stored(self) -> None:
        """tool_calls list is stored when provided."""
        calls = [{"id": "tc-1", "function": {"name": "shell", "arguments": "{}"}}]
        msg = Message(role="assistant", content="", tool_calls=calls)
        assert msg.tool_calls == calls
        assert len(msg.tool_calls) == 1

    def test_tool_call_id_stored(self) -> None:
        """tool_call_id is stored on tool-response messages."""
        msg = Message(role="tool", content="result", tool_call_id="tc-1")
        assert msg.tool_call_id == "tc-1"


@pytest.mark.unit
class TestToDict:
    """Message.to_dict() produces provider-compatible dicts."""

    def test_basic_message_to_dict(self) -> None:
        """A simple message serializes to role + content keys only."""
        msg = Message(role="user", content="do something")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "do something"}
        assert "tool_calls" not in d
        assert "tool_call_id" not in d

    def test_tool_calls_included_when_present(self) -> None:
        """to_dict() includes tool_calls when non-empty."""
        calls = [{"id": "tc-1", "function": {"name": "file_read", "arguments": '{"path":"a"}'}}]
        msg = Message(role="assistant", content="", tool_calls=calls)
        d = msg.to_dict()
        assert "tool_calls" in d
        assert d["tool_calls"] is calls

    def test_tool_call_id_included_when_present(self) -> None:
        """to_dict() includes tool_call_id when set."""
        msg = Message(role="tool", content="ok", tool_call_id="tc-1")
        d = msg.to_dict()
        assert d["tool_call_id"] == "tc-1"

    def test_empty_tool_calls_list_omitted(self) -> None:
        """An empty tool_calls list is falsy and omitted from the dict."""
        msg = Message(role="assistant", content="done", tool_calls=[])
        d = msg.to_dict()
        assert "tool_calls" not in d


@pytest.mark.unit
class TestFromDict:
    """Message.from_dict() round-trips correctly."""

    def test_round_trip_basic(self) -> None:
        """from_dict(to_dict()) produces an equivalent Message."""
        original = Message(role="user", content="test")
        rebuilt = Message.from_dict(original.to_dict())
        assert rebuilt.role == original.role
        assert rebuilt.content == original.content

    def test_round_trip_with_tool_calls(self) -> None:
        """Round-trip preserves tool_calls."""
        calls = [{"id": "tc-2", "function": {"name": "shell", "arguments": '{"cmd":"ls"}'}}]
        original = Message(role="assistant", content="", tool_calls=calls)
        rebuilt = Message.from_dict(original.to_dict())
        assert rebuilt.tool_calls == calls

    def test_from_empty_dict_uses_defaults(self) -> None:
        """from_dict({}) returns a Message with empty-string defaults."""
        msg = Message.from_dict({})
        assert msg.role == ""
        assert msg.content == ""
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_from_dict_ignores_extra_keys(self) -> None:
        """Extra keys in the dict are silently ignored."""
        msg = Message.from_dict({"role": "system", "content": "hi", "extra_key": 42})
        assert msg.role == "system"
        assert msg.content == "hi"
