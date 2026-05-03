"""SQLite storage layer for Guild — single source of truth.

All persistent state (tasks, agents, messages, audit logs, learnings)
is stored in a single SQLite database with WAL mode for concurrent reads.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

__all__ = ["Storage"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    acceptance_criteria TEXT DEFAULT '[]',
    parent_task_id TEXT,
    assigned_agent TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    block_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    task_id TEXT,
    created_at TEXT NOT NULL,
    token_input INTEGER DEFAULT 0,
    token_output INTEGER DEFAULT 0
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

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    block_scope TEXT,
    created_at TEXT NOT NULL,
    last_validated TEXT,
    source_task_id TEXT
);
"""


class Storage:
    """Async SQLite storage for Guild.

    Provides CRUD operations for all persistent state. Uses WAL mode
    for concurrent reads during agent execution.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and initialize schema."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        """Get the active database connection.

        Raises:
            AssertionError: If connect() has not been called.
        """
        assert self._db is not None, "Storage not connected. Call connect() first."
        return self._db

    # --- Tasks ---

    async def create_task(self, task_id: str, description: str, **kwargs: str) -> None:
        """Create a new task.

        Args:
            task_id: Unique task identifier.
            description: Human-readable task description.
        """
        await self.db.execute(
            "INSERT INTO tasks (task_id, description, status, created_at) VALUES (?, ?, 'pending', ?)",
            (task_id, description, datetime.now().isoformat()),
        )
        await self.db.commit()

    async def get_task(self, task_id: str) -> dict | None:
        """Get a task by ID.

        Args:
            task_id: Task identifier.

        Returns:
            Task dict or None if not found.
        """
        async with self.db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        """List tasks, optionally filtered by status.

        Args:
            status: Filter by this status (None = all tasks).

        Returns:
            List of task dicts, newest first.
        """
        if status:
            sql, params = "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status,)
        else:
            sql, params = "SELECT * FROM tasks ORDER BY created_at DESC", ()
        async with self.db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update task fields.

        Args:
            task_id: Task identifier.
            **fields: Field name/value pairs to update.
        """
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [task_id]
        await self.db.execute(f"UPDATE tasks SET {sets} WHERE task_id = ?", vals)
        await self.db.commit()

    # --- Agents ---

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent.

        Args:
            agent_id: Unique agent identifier.
            block_name: Name of the block this agent instantiates.
        """
        await self.db.execute(
            "INSERT INTO agents (agent_id, block_name, status, created_at) VALUES (?, ?, 'idle', ?)",
            (agent_id, block_name, datetime.now().isoformat()),
        )
        await self.db.commit()

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update agent fields.

        Args:
            agent_id: Agent identifier.
            **fields: Field name/value pairs to update.
        """
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [agent_id]
        await self.db.execute(f"UPDATE agents SET {sets} WHERE agent_id = ?", vals)
        await self.db.commit()

    async def list_agents(self) -> list[dict]:
        """List all agents, newest first.

        Returns:
            List of agent dicts.
        """
        async with self.db.execute("SELECT * FROM agents ORDER BY created_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Messages ---

    async def append_message(
        self, agent_id: str, role: str, content: str, **kwargs: str
    ) -> None:
        """Append a message to an agent's conversation history.

        Args:
            agent_id: Agent identifier.
            role: Message role ('system', 'user', 'assistant', 'tool').
            content: Message text.
            **kwargs: Optional tool_call_id and tool_calls.
        """
        await self.db.execute(
            "INSERT INTO messages (agent_id, role, content, tool_call_id, tool_calls, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                agent_id, role, content,
                kwargs.get("tool_call_id"),
                json.dumps(kwargs.get("tool_calls")) if kwargs.get("tool_calls") else None,
                datetime.now().isoformat(),
            ),
        )
        await self.db.commit()

    async def get_messages(self, agent_id: str) -> list[dict]:
        """Get all messages for an agent, in order.

        Args:
            agent_id: Agent identifier.

        Returns:
            List of message dicts.
        """
        async with self.db.execute(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY id", (agent_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Audit ---

    async def log_audit(
        self, action: str, agent_id: str | None = None, details: str | None = None
    ) -> None:
        """Log an audit event.

        Args:
            action: Action name (e.g., 'tool_call', 'permission_check').
            agent_id: Agent that performed the action.
            details: JSON-serializable details string.
        """
        await self.db.execute(
            "INSERT INTO audit_log (agent_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, action, details, datetime.now().isoformat()),
        )
        await self.db.commit()

    async def list_audit(self, limit: int = 50) -> list[dict]:
        """List audit log entries, newest first.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of audit log dicts.
        """
        async with self.db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Learnings ---

    async def add_learning(
        self,
        category: str,
        content: str,
        confidence: float = 0.5,
        block_scope: str | None = None,
        source_task_id: str | None = None,
    ) -> None:
        """Store a learning extracted from a completed task.

        Args:
            category: Learning type ('pattern', 'anti_pattern', 'tool_tip', 'domain_knowledge').
            content: Concise, actionable description.
            confidence: Confidence score (0.0 to 1.0).
            block_scope: Block this learning applies to (None = global).
            source_task_id: Task this learning was extracted from.
        """
        now = datetime.now().isoformat()
        await self.db.execute(
            "INSERT INTO learnings "
            "(category, content, confidence, block_scope, created_at, last_validated, source_task_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (category, content, confidence, block_scope, now, now, source_task_id),
        )
        await self.db.commit()

    async def list_learnings(self, min_confidence: float = 0.0) -> list[dict]:
        """List learnings, optionally filtered by minimum confidence.

        Args:
            min_confidence: Minimum confidence threshold.

        Returns:
            List of learning dicts, highest confidence first.
        """
        async with self.db.execute(
            "SELECT * FROM learnings WHERE confidence >= ? ORDER BY confidence DESC",
            (min_confidence,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
