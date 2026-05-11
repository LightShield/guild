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

    async def test_receive_timeout_zero_returns_immediately(self) -> None:
        """receive() with timeout=0 returns None immediately if no message."""
        import time

        bus = MessageBus()
        start = time.monotonic()
        result = await bus.receive("agent-nobody", timeout=0.0)
        elapsed = time.monotonic() - start

        assert result is None
        # Should return near-instantly (asyncio.wait_for with 0 timeout)
        assert elapsed < 0.1

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


@pytest.mark.unit
@pytest.mark.req("REQ-04.10")
@pytest.mark.req("REQ-07.3")
class TestSharedContext:
    """SharedContext provides a shared workspace for team members."""

    async def test_shared_context_put_and_get(self) -> None:
        """Data stored in shared context is retrievable by any agent."""
        from guild.orchestration.bus import SharedContext

        ctx = SharedContext()
        ctx.put("design-doc", {"title": "Architecture", "version": 2}, "agent-a")

        result = ctx.get("design-doc")
        assert result is not None
        assert result["title"] == "Architecture"
        assert result["version"] == 2

    async def test_shared_context_list_keys(self) -> None:
        """All shared context keys can be listed."""
        from guild.orchestration.bus import SharedContext

        ctx = SharedContext()
        ctx.put("file-list", {"files": ["a.py", "b.py"]}, "agent-1")
        ctx.put("config", {"debug": True}, "agent-2")

        keys = ctx.list_keys()
        assert "file-list" in keys
        assert "config" in keys
        assert len(keys) == 2

    async def test_shared_context_get_missing_returns_none(self) -> None:
        """Getting a non-existent key returns None."""
        from guild.orchestration.bus import SharedContext

        ctx = SharedContext()
        assert ctx.get("nonexistent") is None


@pytest.mark.unit
@pytest.mark.req("REQ-04.11")
class TestDynamicWorkerSpawning:
    """Dynamic worker spawning during execution."""

    async def test_dynamic_worker_spawning(self) -> None:
        """Spawner can create agents on the fly during execution."""
        from unittest.mock import AsyncMock

        from guild.orchestration.spawner import AgentSpawner
        from guild.provider.base import LLMResponse

        provider = AsyncMock()
        provider.generate.return_value = LLMResponse(
            content="Worker result",
            tool_calls=None,
            input_tokens=10,
            output_tokens=5,
            model="mock-model",
        )
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        # Spawn workers dynamically during execution
        result1 = await spawner.spawn(task="Subtask A", agent_id="dynamic-1")
        result2 = await spawner.spawn(task="Subtask B", agent_id="dynamic-2")

        assert result1 == "Worker result"
        assert result2 == "Worker result"
        assert "dynamic-1" in spawner.active_agents
        assert "dynamic-2" in spawner.active_agents
        # Can spawn more after initial ones complete
        result3 = await spawner.spawn(task="Subtask C", agent_id="dynamic-3")
        assert result3 == "Worker result"
        assert len(spawner.active_agents) == 3
