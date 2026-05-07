"""In-process async message bus for agent-to-agent communication (REQ-04.7)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["BusMessage", "MessageBus", "SharedContext"]


@dataclass
class BusMessage:
    """A message sent between agents via the bus."""

    source_agent: str
    target_agent: str
    port: str
    data: dict
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MessageBus:
    """In-process async message bus for agent-to-agent communication.

    Each agent has an independent asyncio.Queue. Messages are logged
    for audit and replay.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[BusMessage]] = defaultdict(asyncio.Queue)
        self._log: list[BusMessage] = []

    async def send(self, source: str, target: str, port: str, data: dict) -> None:
        """Send a message from one agent to another."""
        msg = BusMessage(
            source_agent=source,
            target_agent=target,
            port=port,
            data=data,
        )
        self._log.append(msg)
        await self._queues[target].put(msg)

    async def receive(self, agent_id: str, timeout: float | None = None) -> BusMessage | None:
        """Receive next message for an agent.

        Returns None if timeout expires before a message arrives.
        """
        queue = self._queues[agent_id]
        try:
            if timeout is not None:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            return await queue.get()
        except TimeoutError:
            return None

    def has_pending(self, agent_id: str) -> bool:
        """Check if an agent has unread messages in its queue."""
        return not self._queues[agent_id].empty()

    async def broadcast(
        self,
        source: str,
        port: str,
        data: dict,
        exclude: set[str] | None = None,
    ) -> None:
        """Send a message to all known agents except those in exclude.

        The source agent is always excluded from receiving its own
        broadcast.
        """
        excluded = exclude or set()
        excluded.add(source)
        targets = [agent_id for agent_id in self._queues if agent_id not in excluded]
        for target in targets:
            await self.send(source, target, port, data)

    def get_log(self) -> list[BusMessage]:
        """Return all messages sent through the bus (for audit/replay)."""
        return list(self._log)


class SharedContext:
    """Shared workspace context for team members (REQ-04.10).

    Provides a key-value store accessible to all agents in a team,
    enabling shared state without direct message passing.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def put(self, key: str, data: dict, agent_id: str) -> None:
        """Store data accessible to all team members."""
        self._store[key] = data

    def get(self, key: str) -> dict | None:
        """Retrieve shared data by key."""
        return self._store.get(key)

    def list_keys(self) -> list[str]:
        """List all available keys."""
        return list(self._store.keys())
