"""Internal message bus for agent-to-agent communication.

Simple in-process async bus with per-agent queues. No HTTP overhead.
All messages are logged for audit and replay.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from guild.core.models import BusMessage

__all__ = ["MessageBus"]


class MessageBus:
    """In-process async message bus.

    Messages are queued per-agent and logged for audit/replay.
    No network overhead — direct async queue operations.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[BusMessage]] = defaultdict(asyncio.Queue)
        self._log: list[BusMessage] = []

    async def send(self, source: str, target: str, port: str, data: dict) -> None:
        """Send a message from one agent to another.

        Args:
            source: Sending agent ID.
            target: Receiving agent ID.
            port: Named port for the data.
            data: Message payload.
        """
        msg = BusMessage(source_agent=source, target_agent=target, port=port, data=data)
        self._log.append(msg)
        await self._queues[target].put(msg)

    async def receive(self, agent_id: str, timeout: float | None = None) -> BusMessage | None:
        """Receive the next message for an agent.

        Args:
            agent_id: Agent ID to receive for.
            timeout: Max seconds to wait (None = wait forever).

        Returns:
            The next message, or None if timeout expired.
        """
        try:
            return await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def has_pending(self, agent_id: str) -> bool:
        """Check if an agent has pending messages.

        Args:
            agent_id: Agent ID to check.

        Returns:
            True if there are unread messages.
        """
        return not self._queues[agent_id].empty()

    async def broadcast(
        self, source: str, port: str, data: dict, exclude: set[str] | None = None
    ) -> None:
        """Send a message to all known agents.

        Args:
            source: Sending agent ID.
            port: Named port for the data.
            data: Message payload.
            exclude: Agent IDs to skip.
        """
        exclude = exclude or set()
        for agent_id in list(self._queues):
            if agent_id not in exclude:
                await self.send(source, agent_id, port, data)

    def get_log(self) -> list[BusMessage]:
        """Get all messages sent through the bus.

        Returns:
            Copy of the message log.
        """
        return list(self._log)
