"""SQLite-backed persistence layer for Guild state.

Uses aiosqlite with WAL mode for concurrent read access and crash safety.
All state — tasks, agents, messages, audit log, decisions — lives in a
single SQLite file.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["Storage"]

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_agent TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    block_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL,
    token_input INTEGER NOT NULL DEFAULT 0,
    token_output INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_call_id TEXT,
    tool_calls TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT,
    action TEXT NOT NULL,
    details TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    agent_id TEXT,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL,
    alternatives TEXT,
    reversible BOOLEAN DEFAULT 1,
    timestamp TEXT NOT NULL
);
"""


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class Storage:
    """Async SQLite storage for Guild state.

    Usage::

        store = Storage(Path(".guild/guild.db"))
        await store.connect()
        # ... use store ...
        await store.close()
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database, enable WAL mode, and create schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        logger.debug("Storage connected: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def create_task(self, task_id: str, description: str) -> None:
        """Insert a new task with pending status."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO tasks (task_id, description, created_at) VALUES (?, ?, ?)",
            (task_id, description, _now()),
        )
        await self._db.commit()

    async def get_task(self, task_id: str) -> dict | None:
        """Retrieve a task by ID, or None if not found."""
        assert self._db is not None
        cursor = await self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        """List all tasks, optionally filtered by status."""
        assert self._db is not None
        if status is None:
            cursor = await self._db.execute("SELECT * FROM tasks")
        else:
            cursor = await self._db.execute("SELECT * FROM tasks WHERE status = ?", (status,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update one or more fields on an existing task."""
        assert self._db is not None
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

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO agents (agent_id, block_name, created_at) VALUES (?, ?, ?)",
            (agent_id, block_name, _now()),
        )
        await self._db.commit()

    async def list_agents(self) -> list[dict]:
        """List all registered agents."""
        assert self._db is not None
        cursor = await self._db.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update one or more fields on an existing agent."""
        assert self._db is not None
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

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(self, agent_id: str, role: str, content: str, **kwargs: str) -> None:
        """Append a message to the agent's conversation history."""
        assert self._db is not None
        tool_call_id = kwargs.get("tool_call_id")
        tool_calls = kwargs.get("tool_calls")
        await self._db.execute(
            "INSERT INTO messages (agent_id, role, content, tool_call_id, tool_calls, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, role, content, tool_call_id, tool_calls, _now()),
        )
        await self._db.commit()

    async def get_messages(self, agent_id: str) -> list[dict]:
        """Get all messages for an agent, ordered by insertion."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY id ASC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log an audit event."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO audit_log (agent_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, action, details, _now()),
        )
        await self._db.commit()

    async def list_audit(self, limit: int = 50) -> list[dict]:
        """List audit entries, most recent first."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    async def log_decision(
        self,
        task_id: str | None,
        agent_id: str | None,
        decision: str,
        rationale: str,
        alternatives: list[str] | None = None,
        *,
        reversible: bool = True,
    ) -> None:
        """Record a non-trivial decision with rationale."""
        assert self._db is not None
        alts_json = json.dumps(alternatives) if alternatives else None
        await self._db.execute(
            "INSERT INTO decisions"
            " (task_id, agent_id, decision, rationale,"
            "  alternatives, reversible, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                agent_id,
                decision,
                rationale,
                alts_json,
                reversible,
                _now(),
            ),
        )
        await self._db.commit()

    async def list_decisions(
        self,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List decisions, most recent first, optionally by task."""
        assert self._db is not None
        if task_id is None:
            cursor = await self._db.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM decisions"
                " WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_tables(self) -> list[str]:
        """Return list of table names (used in tests)."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
