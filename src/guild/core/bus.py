"""Internal message bus for agent-to-agent communication."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from guild.core.models import BusMessage


class MessageBus:
    """Simple in-process async message bus.

    No HTTP, no serialization overhead. Messages are queued per-agent
    and logged for audit/replay.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[BusMessage]] = defaultdict(asyncio.Queue)
        self._log: list[BusMessage] = []

    async def send(self, source: str, target: str, port: str, data: dict) -> None:
        msg = BusMessage(source_agent=source, target_agent=target, port=port, data=data)
        self._log.append(msg)
        await self._queues[target].put(msg)

    async def receive(self, agent_id: str, timeout: float | None = None) -> BusMessage | None:
        try:
            return await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def has_pending(self, agent_id: str) -> bool:
        return not self._queues[agent_id].empty()

    async def broadcast(self, source: str, port: str, data: dict, exclude: set[str] | None = None) -> None:
        exclude = exclude or set()
        for agent_id in list(self._queues):
            if agent_id not in exclude:
                await self.send(source, agent_id, port, data)

    def get_log(self) -> list[BusMessage]:
        return list(self._log)
