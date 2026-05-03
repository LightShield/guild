"""Tests for core/bus.py — send/receive, broadcast, queue isolation."""

import pytest
import asyncio

from guild.core.bus import MessageBus


class TestMessageBus:
    async def test_send_and_receive(self):
        bus = MessageBus()
        await bus.send("a1", "a2", "output", {"result": "hello"})
        msg = await bus.receive("a2", timeout=1.0)
        assert msg is not None
        assert msg.source_agent == "a1"
        assert msg.port == "output"
        assert msg.data == {"result": "hello"}

    async def test_receive_timeout(self):
        bus = MessageBus()
        msg = await bus.receive("a1", timeout=0.1)
        assert msg is None

    async def test_queue_isolation(self):
        bus = MessageBus()
        await bus.send("a1", "a2", "p1", {"for": "a2"})
        await bus.send("a1", "a3", "p1", {"for": "a3"})
        msg2 = await bus.receive("a2", timeout=1.0)
        msg3 = await bus.receive("a3", timeout=1.0)
        assert msg2.data == {"for": "a2"}
        assert msg3.data == {"for": "a3"}

    async def test_has_pending(self):
        bus = MessageBus()
        assert bus.has_pending("a1") is False
        await bus.send("x", "a1", "p", {})
        assert bus.has_pending("a1") is True
        await bus.receive("a1", timeout=1.0)
        assert bus.has_pending("a1") is False

    async def test_broadcast(self):
        bus = MessageBus()
        # Pre-create queues by sending a dummy message
        await bus.send("setup", "a1", "p", {})
        await bus.send("setup", "a2", "p", {})
        await bus.receive("a1", timeout=0.1)
        await bus.receive("a2", timeout=0.1)

        await bus.broadcast("sender", "notify", {"msg": "hi"}, exclude=set())
        msg1 = await bus.receive("a1", timeout=1.0)
        msg2 = await bus.receive("a2", timeout=1.0)
        assert msg1 is not None
        assert msg2 is not None

    async def test_broadcast_with_exclude(self):
        bus = MessageBus()
        await bus.send("setup", "a1", "p", {})
        await bus.send("setup", "a2", "p", {})
        await bus.receive("a1", timeout=0.1)
        await bus.receive("a2", timeout=0.1)

        await bus.broadcast("sender", "notify", {"msg": "hi"}, exclude={"a1"})
        msg1 = await bus.receive("a1", timeout=0.1)
        msg2 = await bus.receive("a2", timeout=1.0)
        assert msg1 is None  # excluded
        assert msg2 is not None

    async def test_log_records_all_messages(self):
        bus = MessageBus()
        await bus.send("a1", "a2", "p1", {"x": 1})
        await bus.send("a2", "a3", "p2", {"x": 2})
        log = bus.get_log()
        assert len(log) == 2
        assert log[0].source_agent == "a1"
        assert log[1].target_agent == "a3"

    async def test_fifo_order(self):
        bus = MessageBus()
        await bus.send("a1", "a2", "p", {"seq": 1})
        await bus.send("a1", "a2", "p", {"seq": 2})
        await bus.send("a1", "a2", "p", {"seq": 3})
        m1 = await bus.receive("a2", timeout=1.0)
        m2 = await bus.receive("a2", timeout=1.0)
        m3 = await bus.receive("a2", timeout=1.0)
        assert m1.data["seq"] == 1
        assert m2.data["seq"] == 2
        assert m3.data["seq"] == 3
