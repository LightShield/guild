"""Tests for orchestration/bus.py — message bus (REQ-04.7)."""

from __future__ import annotations

import pytest

from guild.orchestration.bus import MessageBus


@pytest.mark.unit
@pytest.mark.req("REQ-04.7")
class TestMessageBus:
    """MessageBus delivers messages between agents asynchronously."""

    async def test_send_delivers_message_to_target(self) -> None:
        """A message sent to a target arrives in that target's queue."""
        bus = MessageBus()
        await bus.send("agent-a", "agent-b", "output", {"result": "hello"})

        msg = await bus.receive("agent-b", timeout=1.0)
        assert msg is not None
        assert msg.source_agent == "agent-a"
        assert msg.target_agent == "agent-b"
        assert msg.port == "output"
        assert msg.data == {"result": "hello"}

    async def test_receive_returns_none_on_timeout(self) -> None:
        """receive() returns None when no message arrives before timeout."""
        bus = MessageBus()
        result = await bus.receive("agent-x", timeout=0.05)
        assert result is None

    async def test_has_pending_true_when_messages_queued(self) -> None:
        """has_pending returns True when messages are waiting."""
        bus = MessageBus()
        assert not bus.has_pending("agent-a")

        await bus.send("agent-b", "agent-a", "data", {"x": 1})
        assert bus.has_pending("agent-a")

        # After receiving, no longer pending
        await bus.receive("agent-a", timeout=1.0)
        assert not bus.has_pending("agent-a")

    async def test_broadcast_sends_to_all_except_source(self) -> None:
        """broadcast() delivers to all known agents except the source."""
        bus = MessageBus()
        # Prime the queues so the bus knows about these agents
        await bus.send("setup", "agent-a", "init", {})
        await bus.send("setup", "agent-b", "init", {})
        await bus.send("setup", "agent-c", "init", {})

        # Drain the setup messages
        await bus.receive("agent-a", timeout=0.1)
        await bus.receive("agent-b", timeout=0.1)
        await bus.receive("agent-c", timeout=0.1)

        # Broadcast from agent-a
        await bus.broadcast("agent-a", "announce", {"msg": "hi"})

        # agent-b and agent-c should receive it
        msg_b = await bus.receive("agent-b", timeout=1.0)
        msg_c = await bus.receive("agent-c", timeout=1.0)
        assert msg_b is not None
        assert msg_b.data == {"msg": "hi"}
        assert msg_c is not None
        assert msg_c.data == {"msg": "hi"}

        # agent-a should NOT receive its own broadcast
        msg_a = await bus.receive("agent-a", timeout=0.05)
        assert msg_a is None

    async def test_messages_logged_for_audit(self) -> None:
        """All sent messages are recorded in the audit log."""
        bus = MessageBus()
        await bus.send("a", "b", "port1", {"k": "v1"})
        await bus.send("b", "a", "port2", {"k": "v2"})

        log = bus.get_log()
        assert len(log) == 2
        assert log[0].source_agent == "a"
        assert log[0].target_agent == "b"
        assert log[1].source_agent == "b"
        assert log[1].target_agent == "a"

    async def test_multiple_agents_independent_queues(self) -> None:
        """Messages to different agents go to separate queues."""
        bus = MessageBus()
        await bus.send("src", "agent-1", "p", {"for": "1"})
        await bus.send("src", "agent-2", "p", {"for": "2"})
        await bus.send("src", "agent-1", "p", {"for": "1b"})

        # agent-1 gets its two messages
        m1 = await bus.receive("agent-1", timeout=1.0)
        m2 = await bus.receive("agent-1", timeout=1.0)
        assert m1 is not None
        assert m1.data == {"for": "1"}
        assert m2 is not None
        assert m2.data == {"for": "1b"}

        # agent-2 gets its one message
        m3 = await bus.receive("agent-2", timeout=1.0)
        assert m3 is not None
        assert m3.data == {"for": "2"}

        # No more messages
        assert not bus.has_pending("agent-1")
        assert not bus.has_pending("agent-2")
