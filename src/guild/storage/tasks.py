"""Task CRUD operations for Guild storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from guild.storage.connection import DBConnection
from logger_python import get_logger

__all__ = ["TaskOps"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class TaskOps:
    """Task and agent persistence operations."""

    def __init__(self, db: DBConnection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def create_task(self, task_id: str, description: str) -> None:
        """Insert a new task with pending status."""
        await self._db.execute(
            "INSERT INTO tasks (task_id, description, created_at) VALUES (?, ?, ?)",
            (task_id, description, _now()),
        )
        await self._db.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a task by ID, or None if not found."""
        cursor = await self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        if status is None:
            cursor = await self._db.execute("SELECT * FROM tasks")
        else:
            cursor = await self._db.execute("SELECT * FROM tasks WHERE status = ?", (status,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update one or more fields on an existing task."""
        if not fields:
            return
        allowed = {"status", "assigned_agent", "completed_at", "result"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [task_id]
        await self._db.execute(
            f"UPDATE tasks SET {set_clause} WHERE task_id = ?", values  # noqa: S608
        )
        await self._db.commit()

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent."""
        await self._db.execute(
            "INSERT INTO agents (agent_id, block_name, created_at) VALUES (?, ?, ?)",
            (agent_id, block_name, _now()),
        )
        await self._db.commit()

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        cursor = await self._db.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update one or more fields on an existing agent."""
        if not fields:
            return
        allowed = {"status", "token_input", "token_output"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [agent_id]
        await self._db.execute(
            f"UPDATE agents SET {set_clause} WHERE agent_id = ?", values  # noqa: S608
        )
        await self._db.commit()
