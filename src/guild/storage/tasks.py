"""Task CRUD operations for Guild storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

if TYPE_CHECKING:
    from guild.storage.connection import DBConnection

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

    async def add_task_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        agent_id: str | None = None,
        block_name: str | None = None,
    ) -> None:
        """Append a task timeline event."""
        await self._db.execute(
            "INSERT INTO task_events"
            " (task_id, event_type, message, agent_id, block_name, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, event_type, message, agent_id, block_name, _now()),
        )
        await self._db.commit()

    async def list_task_events(
        self, task_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List task timeline events, newest last."""
        if task_id is None:
            cursor = await self._db.execute(
                "SELECT * FROM task_events ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            fetched_rows = list(await cursor.fetchall())
            rows = list(reversed(fetched_rows))
        else:
            cursor = await self._db.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC LIMIT ?",
                (task_id, limit),
            )
            rows = list(await cursor.fetchall())
        return [dict(r) for r in rows]

    async def register_agent(
        self, agent_id: str, block_name: str, task_id: str | None = None
    ) -> None:
        """Register a new agent."""
        await self._db.execute(
            "INSERT INTO agents (agent_id, block_name, created_at, task_id, last_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (agent_id, block_name, _now(), task_id, _now()),
        )
        await self._db.commit()

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        cursor = await self._db.execute("SELECT * FROM agents ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update one or more fields on an existing agent."""
        if not fields:
            return
        allowed = {"status", "token_input", "token_output", "task_id", "last_seen"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        filtered.setdefault("last_seen", _now())
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [agent_id]
        await self._db.execute(
            f"UPDATE agents SET {set_clause} WHERE agent_id = ?", values  # noqa: S608
        )
        await self._db.commit()
