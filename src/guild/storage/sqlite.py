"""SQLite-backed persistence layer for Guild state.

Uses aiosqlite with WAL mode for concurrent read access and crash safety.
All state — tasks, agents, messages, audit log, decisions — lives in a
single SQLite file.
"""

from __future__ import annotations

import json
from logger_python import get_logger
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiosqlite

from guild.config.constants import (
    CONFIDENCE_DECAY_DECREMENT,
    CONFIDENCE_INVALIDATE_DECREMENT,
    CONFIDENCE_VALIDATE_INCREMENT,
    MEMORY_SUMMARY_MAX_CHARS,
)

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from pathlib import Path

__all__ = [
    "CONFIDENCE_DECAY_DECREMENT",
    "CONFIDENCE_INVALIDATE_DECREMENT",
    "CONFIDENCE_VALIDATE_INCREMENT",
    "DecisionRecord",
    "LearningRecord",
    "MEMORY_SUMMARY_MAX_CHARS",
    "QuestionRecord",
    "Storage",
]


@dataclass
class DecisionRecord:
    """Record of a non-trivial decision with rationale."""

    decision: str
    rationale: str
    task_id: str | None = None
    agent_id: str | None = None
    alternatives: list[str] | None = None
    reversible: bool = True


@dataclass
class LearningRecord:
    """Record for a new learning entry."""

    category: str
    content: str
    confidence: float = 0.3
    scope: str | None = None
    source_task_id: str | None = None


@dataclass
class QuestionRecord:
    """Record for an escalation question."""

    question_id: str
    question: str
    context: str
    created_at: str
    task_id: str | None = None
    agent_id: str | None = None
    priority: str = "normal"

logger = get_logger(__name__)

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

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.3,
    scope TEXT,
    source_task_id TEXT,
    created_at TEXT NOT NULL,
    last_validated TEXT,
    validation_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT,
    question TEXT NOT NULL,
    context TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    created_at TEXT NOT NULL,
    answered INTEGER DEFAULT 0,
    answer TEXT,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    verified INTEGER DEFAULT 0,
    last_verified TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    model TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    task_completed INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    turns INTEGER NOT NULL,
    error TEXT,
    timestamp TEXT NOT NULL
);
"""


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class Storage:
    """Async SQLite storage for Guild state.

    Usage::

        from guild.config.loader import DB_FILENAME
        store = Storage(Path(".guild") / DB_FILENAME)
        await store.connect()
        # ... use store ...
        await store.close()
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Storage:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "INSERT INTO tasks (task_id, description, created_at) VALUES (?, ?, ?)",
            (task_id, description, _now()),
        )
        await self._db.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a task by ID, or None if not found."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if status is None:
            cursor = await self._db.execute("SELECT * FROM tasks")
        else:
            cursor = await self._db.execute("SELECT * FROM tasks WHERE status = ?", (status,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update one or more fields on an existing task."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "INSERT INTO agents (agent_id, block_name, created_at) VALUES (?, ?, ?)",
            (agent_id, block_name, _now()),
        )
        await self._db.commit()

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update one or more fields on an existing agent."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "INSERT INTO audit_log (agent_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, action, details, _now()),
        )
        await self._db.commit()

    async def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        """List audit entries, most recent first."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        record: DecisionRecord | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        decision: str = "",
        rationale: str = "",
        alternatives: list[str] | None = None,
        *,
        reversible: bool = True,
    ) -> None:
        """Record a non-trivial decision with rationale."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if record is None:
            record = DecisionRecord(
                decision=decision,
                rationale=rationale,
                task_id=task_id,
                agent_id=agent_id,
                alternatives=alternatives,
                reversible=reversible,
            )
        alts_json = json.dumps(record.alternatives) if record.alternatives else None
        await self._db.execute(
            "INSERT INTO decisions"
            " (task_id, agent_id, decision, rationale,"
            "  alternatives, reversible, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.task_id,
                record.agent_id,
                record.decision,
                record.rationale,
                alts_json,
                record.reversible,
                _now(),
            ),
        )
        await self._db.commit()

    async def list_decisions(
        self,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List decisions, most recent first, optionally by task."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if task_id is None:
            cursor = await self._db.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM decisions" " WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Learnings
    # ------------------------------------------------------------------

    async def add_learning(
        self,
        record: LearningRecord | None = None,
        category: str = "",
        content: str = "",
        confidence: float = 0.3,
        scope: str | None = None,
        source_task_id: str | None = None,
    ) -> int:
        """Insert a new learning and return its ID."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if record is None:
            record = LearningRecord(
                category=category,
                content=content,
                confidence=confidence,
                scope=scope,
                source_task_id=source_task_id,
            )
        cursor = await self._db.execute(
            "INSERT INTO learnings"
            " (category, content, confidence, scope, source_task_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.category,
                record.content,
                record.confidence,
                record.scope,
                record.source_task_id,
                _now(),
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def list_learnings(
        self,
        min_confidence: float = 0.0,
        category: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List learnings filtered by confidence, category, and scope."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        query = "SELECT * FROM learnings WHERE confidence >= ?"
        params: list[Any] = [min_confidence]

        if category is not None:
            query += " AND category = ?"
            params.append(category)
        if scope is not None:
            query += " AND scope = ?"
            params.append(scope)

        query += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def validate_learning(self, learning_id: int) -> None:
        """Increase confidence by CONFIDENCE_VALIDATE_INCREMENT (capped at 1.0)."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "UPDATE learnings SET"
            " confidence = MIN(confidence + ?, 1.0),"
            " last_validated = ?,"
            " validation_count = validation_count + 1"
            " WHERE id = ?",
            (CONFIDENCE_VALIDATE_INCREMENT, _now(), learning_id),
        )
        await self._db.commit()

    async def invalidate_learning(self, learning_id: int) -> None:
        """Decrease confidence by CONFIDENCE_INVALIDATE_DECREMENT (floored at 0.0)."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "UPDATE learnings SET confidence = MAX(confidence - ?, 0.0) WHERE id = ?",
            (CONFIDENCE_INVALIDATE_DECREMENT, learning_id),
        )
        await self._db.commit()

    async def decay_learnings(self, days_since_validation: int = 30) -> int:
        """Decay confidence by CONFIDENCE_DECAY_DECREMENT for learnings unvalidated for N days.

        Returns the number of affected rows.
        """
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days_since_validation)).isoformat()
        cursor = await self._db.execute(
            "UPDATE learnings SET confidence = MAX(confidence - ?, 0.0)"
            " WHERE (last_validated IS NULL OR last_validated < ?)"
            " AND created_at < ?",
            (CONFIDENCE_DECAY_DECREMENT, cutoff, cutoff),
        )
        await self._db.commit()
        return int(cursor.rowcount)

    async def delete_learning(self, learning_id: int) -> None:
        """Delete a learning by ID."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute("DELETE FROM learnings WHERE id = ?", (learning_id,))
        await self._db.commit()

    async def get_learning(self, learning_id: int) -> dict[str, Any] | None:
        """Retrieve a single learning by ID."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute("SELECT * FROM learnings WHERE id = ?", (learning_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Token usage aggregation (REQ-10.3)
    # ------------------------------------------------------------------

    async def get_token_summary(self) -> dict[str, Any]:
        """Aggregate token usage across all agents.

        Returns a dict with total_input, total_output, agent_count,
        and task_count.
        """
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(token_input), 0) AS total_input,"
            " COALESCE(SUM(token_output), 0) AS total_output,"
            " COUNT(*) AS agent_count"
            " FROM agents"
        )
        row = await cursor.fetchone()
        task_cursor = await self._db.execute("SELECT COUNT(*) FROM tasks")
        task_row = await task_cursor.fetchone()
        # COALESCE/COUNT guarantee non-None rows from aggregate queries
        assert row is not None  # noqa: S101
        assert task_row is not None  # noqa: S101
        return {
            "total_input": row[0],
            "total_output": row[1],
            "agent_count": row[2],
            "task_count": task_row[0],
        }

    # ------------------------------------------------------------------
    # Questions (REQ-15.1)
    # ------------------------------------------------------------------

    async def insert_question(
        self,
        record: QuestionRecord | None = None,
        question_id: str = "",
        question: str = "",
        context: str = "",
        created_at: str = "",
        task_id: str | None = None,
        agent_id: str | None = None,
        priority: str = "normal",
    ) -> None:
        """Insert a new question into the escalation queue."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if record is None:
            record = QuestionRecord(
                question_id=question_id,
                question=question,
                context=context,
                created_at=created_at,
                task_id=task_id,
                agent_id=agent_id,
                priority=priority,
            )
        await self._db.execute(
            "INSERT INTO questions"
            " (id, task_id, agent_id, question, context, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.question_id,
                record.task_id,
                record.agent_id,
                record.question,
                record.context,
                record.priority,
                record.created_at,
            ),
        )
        await self._db.commit()

    async def list_questions(self, answered: bool | None = None) -> list[dict[str, Any]]:
        """List questions, optionally filtered by answered status."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if answered is None:
            cursor = await self._db.execute("SELECT * FROM questions")
        else:
            cursor = await self._db.execute(
                "SELECT * FROM questions WHERE answered = ?",
                (int(answered),),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_question(self, question_id: str) -> dict[str, Any] | None:
        """Retrieve a single question by ID."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def answer_question(self, question_id: str, answer: str) -> None:
        """Mark a question as answered and store the response."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "UPDATE questions SET answered = 1, answer = ?, answered_at = ?" " WHERE id = ?",
            (answer, _now(), question_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Checkpoints (REQ-07.2)
    # ------------------------------------------------------------------

    async def save_checkpoint(self, agent_id: str, task_id: str | None, state_json: str) -> None:
        """Persist an agent checkpoint."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
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
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute(
            "SELECT agent_id, task_id, state_json, created_at"
            " FROM checkpoints WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Memories (REQ-07.5, REQ-07.6, REQ-07.7)
    # ------------------------------------------------------------------

    async def add_memory(self, summary: str, content: str, category: str) -> str:
        """Add a new memory entry. Returns the generated ID."""
        import uuid

        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        memory_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO memories"
            " (id, summary, content, category, verified, last_verified, created_at)"
            " VALUES (?, ?, ?, ?, 0, NULL, ?)",
            (memory_id, summary[:MEMORY_SUMMARY_MAX_CHARS], content, category, _now()),
        )
        await self._db.commit()
        return memory_id

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Retrieve a single memory by ID."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute(
            "SELECT id, summary, content, category, verified, last_verified, created_at"
            " FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_memory_summaries(self, limit: int = 200) -> list[dict[str, Any]]:
        """List memory summaries ordered by last_verified descending.

        Returns list of dicts with keys: id, summary, verified.
        """
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute(
            "SELECT id, summary, verified FROM memories"
            " ORDER BY last_verified DESC NULLS LAST"
            " LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def verify_memory(self, memory_id: str) -> None:
        """Mark a memory as verified against current state."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "UPDATE memories SET verified = 1, last_verified = ? WHERE id = ?",
            (_now(), memory_id),
        )
        await self._db.commit()

    async def consolidate_memories(self, stale_days: int = 30) -> int:
        """Remove stale unverified memories and merge duplicates.

        Returns count of deleted rows.
        """
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")

        changes = await self._remove_stale_memories(stale_days)
        changes += await self._dedup_memories()
        await self._db.commit()
        return changes

    async def _remove_stale_memories(self, stale_days: int) -> int:
        """Delete unverified memories older than stale_days."""
        from datetime import timedelta

        if self._db is None:
            raise RuntimeError("Storage not connected")
        cutoff = (datetime.now(UTC) - timedelta(days=stale_days)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM memories"
            " WHERE verified = 0"
            " AND (last_verified IS NULL OR last_verified < ?)"
            " AND created_at < ?",
            (cutoff, cutoff),
        )
        return int(cursor.rowcount)

    async def _dedup_memories(self) -> int:
        """Merge duplicate summaries: keep most recent, delete the rest."""
        if self._db is None:
            raise RuntimeError("Storage not connected")
        changes = 0
        dup_cursor = await self._db.execute(
            "SELECT summary, COUNT(*) as cnt FROM memories" " GROUP BY summary HAVING cnt > 1"
        )
        duplicates = await dup_cursor.fetchall()
        for dup_row in duplicates:
            summary = dup_row[0]
            entries_cursor = await self._db.execute(
                "SELECT id FROM memories WHERE summary = ?" " ORDER BY created_at DESC",
                (summary,),
            )
            entries = list(await entries_cursor.fetchall())
            ids_to_delete = [e[0] for e in entries[1:]]
            if ids_to_delete:  # pragma: no branch — HAVING cnt>1 guarantees >=2 rows
                placeholders = ",".join("?" * len(ids_to_delete))
                del_cursor = await self._db.execute(
                    f"DELETE FROM memories WHERE id IN ({placeholders})",  # noqa: S608
                    ids_to_delete,
                )
                changes += int(del_cursor.rowcount)
        return changes

    # ------------------------------------------------------------------
    # Eval Results (REQ-16.5)
    # ------------------------------------------------------------------

    async def store_eval_result(self, result_data: dict[str, Any]) -> None:
        """Persist an eval result.

        Expects keys: task_name, model, config_hash, task_completed,
        duration_seconds, input_tokens, output_tokens, tool_calls,
        turns, error, timestamp.
        """
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        await self._db.execute(
            "INSERT INTO eval_results"
            " (task_name, model, config_hash, task_completed,"
            "  duration_seconds, input_tokens, output_tokens,"
            "  tool_calls, turns, error, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result_data["task_name"],
                result_data["model"],
                result_data["config_hash"],
                result_data["task_completed"],
                result_data["duration_seconds"],
                result_data["input_tokens"],
                result_data["output_tokens"],
                result_data["tool_calls"],
                result_data["turns"],
                result_data["error"],
                result_data["timestamp"],
            ),
        )
        await self._db.commit()

    async def list_eval_results(
        self, task_name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List eval results, most recent first, optionally by task_name."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        if task_name is not None:
            cursor = await self._db.execute(
                "SELECT * FROM eval_results" " WHERE task_name = ? ORDER BY id DESC LIMIT ?",
                (task_name, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM eval_results ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_tables(self) -> list[str]:
        """Return list of table names (used in tests)."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
