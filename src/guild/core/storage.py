"""SQLite storage layer for Guild — single source of truth."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

SCHEMA = """
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
    """Async SQLite storage for Guild."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Storage not connected. Call connect() first."
        return self._db

    # --- Tasks ---

    async def create_task(self, task_id: str, description: str, **kwargs: str) -> None:
        await self.db.execute(
            "INSERT INTO tasks (task_id, description, status, created_at) VALUES (?, ?, 'pending', ?)",
            (task_id, description, datetime.now().isoformat()),
        )
        await self.db.commit()

    async def get_task(self, task_id: str) -> dict | None:
        async with self.db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        if status:
            sql, params = "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status,)
        else:
            sql, params = "SELECT * FROM tasks ORDER BY created_at DESC", ()
        async with self.db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def update_task(self, task_id: str, **fields: str) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [task_id]
        await self.db.execute(f"UPDATE tasks SET {sets} WHERE task_id = ?", vals)
        await self.db.commit()

    # --- Agents ---

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        await self.db.execute(
            "INSERT INTO agents (agent_id, block_name, status, created_at) VALUES (?, ?, 'idle', ?)",
            (agent_id, block_name, datetime.now().isoformat()),
        )
        await self.db.commit()

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [agent_id]
        await self.db.execute(f"UPDATE agents SET {sets} WHERE agent_id = ?", vals)
        await self.db.commit()

    async def list_agents(self) -> list[dict]:
        async with self.db.execute("SELECT * FROM agents ORDER BY created_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Messages ---

    async def append_message(self, agent_id: str, role: str, content: str, **kwargs: str) -> None:
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
        async with self.db.execute(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY id", (agent_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # --- Audit ---

    async def log_audit(self, action: str, agent_id: str | None = None, details: str | None = None) -> None:
        await self.db.execute(
            "INSERT INTO audit_log (agent_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, action, details, datetime.now().isoformat()),
        )
        await self.db.commit()

    # --- Learnings ---

    async def add_learning(
        self, category: str, content: str, confidence: float = 0.5,
        block_scope: str | None = None, source_task_id: str | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            "INSERT INTO learnings (category, content, confidence, block_scope, created_at, last_validated, source_task_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (category, content, confidence, block_scope, now, now, source_task_id),
        )
        await self.db.commit()

    async def list_learnings(self, min_confidence: float = 0.0) -> list[dict]:
        async with self.db.execute(
            "SELECT * FROM learnings WHERE confidence >= ? ORDER BY confidence DESC", (min_confidence,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
