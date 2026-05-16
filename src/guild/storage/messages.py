"""Message operations for Guild storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiosqlite
from logger_python import get_logger

__all__ = ["MessageOps"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class MessageOps:
    """Message persistence operations."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def append_message(self, agent_id: str, role: str, content: str, **kwargs: str) -> None:
        """Append a message to the agent's conversation history."""
        tool_call_id = kwargs.get("tool_call_id")
        tool_calls = kwargs.get("tool_calls")
        await self._db.execute(
            "INSERT INTO messages (agent_id, role, content, tool_call_id, tool_calls, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, role, content, tool_call_id, tool_calls, _now()),
        )
        await self._db.commit()

    async def get_messages(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all messages for an agent, ordered by insertion."""
        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY id ASC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
