"""Checkpoint operations for Guild storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from logger_python import get_logger

from guild.storage.connection import DBConnection

__all__ = ["CheckpointOps"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class CheckpointOps:
    """Checkpoint persistence operations."""

    def __init__(self, db: DBConnection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def save_checkpoint(self, agent_id: str, task_id: str | None, state_json: str) -> None:
        """Persist an agent checkpoint."""
        await self._db.execute(
            "INSERT INTO checkpoints (agent_id, task_id, state_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (agent_id, task_id, state_json, _now()),
        )
        await self._db.commit()

    async def load_checkpoint(self, agent_id: str) -> dict[str, Any] | None:
        """Load the most recent checkpoint for an agent.

        Returns a dict with keys: agent_id, task_id, state_json, created_at;
        or None if no checkpoint exists.
        """
        cursor = await self._db.execute(
            "SELECT agent_id, task_id, state_json, created_at"
            " FROM checkpoints WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
