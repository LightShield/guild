"""SQLite-backed persistence layer for Guild state.

Uses aiosqlite with WAL mode for concurrent read access and crash safety.
All state — tasks, agents, messages, audit log, decisions — lives in a
single SQLite file.

This module is the thin coordinator that owns the database connection
and delegates to per-entity operation modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiosqlite
from logger_python import get_logger

from guild.config.constants import DEFAULT_MEMORY_LIST_LIMIT, DEFAULT_QUERY_LIMIT, PRUNING_RETENTION_DAYS
from guild.storage.audit import AuditOps, DecisionRecord
from guild.storage.checkpoints import CheckpointOps
from guild.storage.learnings import LearningOps, LearningRecord
from guild.storage.memories import MemoryOps
from guild.storage.messages import MessageOps
from guild.storage.questions import QuestionOps, QuestionRecord
from guild.storage.tasks import TaskOps

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from pathlib import Path

__all__ = [
    "DecisionRecord",
    "LearningRecord",
    "QuestionRecord",
    "Storage",
]


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
        """Initialize Storage."""
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # Delegates initialized on connect()
        self._tasks: TaskOps | None = None
        self._messages: MessageOps | None = None
        self._audit: AuditOps | None = None
        self._learnings: LearningOps | None = None
        self._questions: QuestionOps | None = None
        self._checkpoints: CheckpointOps | None = None
        self._memories: MemoryOps | None = None

    async def __aenter__(self) -> Storage:
        """Enter async context and connect to the database."""
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit async context and close the database."""
        await self.close()

    async def connect(self) -> None:
        """Open the database, enable WAL mode, and create schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        # Initialize delegates
        self._tasks = TaskOps(self._db)
        self._messages = MessageOps(self._db)
        self._audit = AuditOps(self._db)
        self._learnings = LearningOps(self._db)
        self._questions = QuestionOps(self._db)
        self._checkpoints = CheckpointOps(self._db)
        self._memories = MemoryOps(self._db)
        logger.debug("Storage connected: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_connected(self) -> None:
        """Raise RuntimeError if not connected."""
        if self._db is None:
            raise RuntimeError("Storage not connected. Call connect() first.")

    # ------------------------------------------------------------------
    # Task operations
    # ------------------------------------------------------------------

    async def create_task(self, task_id: str, description: str) -> None:
        """Insert a new task with pending status."""
        self._ensure_connected()
        assert self._tasks is not None
        await self._tasks.create_task(task_id, description)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a task by ID, or None if not found."""
        self._ensure_connected()
        assert self._tasks is not None
        return await self._tasks.get_task(task_id)

    async def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        self._ensure_connected()
        assert self._tasks is not None
        return await self._tasks.list_tasks(status)

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update one or more fields on an existing task."""
        self._ensure_connected()
        assert self._tasks is not None
        await self._tasks.update_task(task_id, **fields)

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent."""
        self._ensure_connected()
        assert self._tasks is not None
        await self._tasks.register_agent(agent_id, block_name)

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        self._ensure_connected()
        assert self._tasks is not None
        return await self._tasks.list_agents()

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update one or more fields on an existing agent."""
        self._ensure_connected()
        assert self._tasks is not None
        await self._tasks.update_agent(agent_id, **fields)

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    async def append_message(self, agent_id: str, role: str, content: str, **kwargs: str) -> None:
        """Append a message to the agent's conversation history."""
        self._ensure_connected()
        assert self._messages is not None
        await self._messages.append_message(agent_id, role, content, **kwargs)

    async def get_messages(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all messages for an agent, ordered by insertion."""
        self._ensure_connected()
        assert self._messages is not None
        return await self._messages.get_messages(agent_id)

    # ------------------------------------------------------------------
    # Audit operations
    # ------------------------------------------------------------------

    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log an audit event."""
        self._ensure_connected()
        assert self._audit is not None
        await self._audit.log_audit(action, agent_id, details)

    async def list_audit(self, limit: int = DEFAULT_QUERY_LIMIT) -> list[dict[str, Any]]:
        """List audit entries, most recent first."""
        self._ensure_connected()
        assert self._audit is not None
        return await self._audit.list_audit(limit)

    async def log_decision(self, record: DecisionRecord) -> None:
        """Record a non-trivial decision with rationale."""
        self._ensure_connected()
        assert self._audit is not None
        await self._audit.log_decision(record)

    async def list_decisions(
        self,
        task_id: str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[dict[str, Any]]:
        """List decisions, most recent first, optionally by task."""
        self._ensure_connected()
        assert self._audit is not None
        return await self._audit.list_decisions(task_id, limit)

    # ------------------------------------------------------------------
    # Learning operations
    # ------------------------------------------------------------------

    async def add_learning(self, record: LearningRecord) -> int:
        """Insert a new learning and return its ID."""
        self._ensure_connected()
        assert self._learnings is not None
        return await self._learnings.add_learning(record)

    async def list_learnings(
        self,
        min_confidence: float = 0.0,
        category: str | None = None,
        scope: str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[dict[str, Any]]:
        """List learnings filtered by confidence, category, and scope."""
        self._ensure_connected()
        assert self._learnings is not None
        return await self._learnings.list_learnings(min_confidence, category, scope, limit)

    async def validate_learning(self, learning_id: int) -> None:
        """Increase confidence by CONFIDENCE_VALIDATE_INCREMENT (capped at 1.0)."""
        self._ensure_connected()
        assert self._learnings is not None
        await self._learnings.validate_learning(learning_id)

    async def invalidate_learning(self, learning_id: int) -> None:
        """Decrease confidence by CONFIDENCE_INVALIDATE_DECREMENT (floored at 0.0)."""
        self._ensure_connected()
        assert self._learnings is not None
        await self._learnings.invalidate_learning(learning_id)

    async def decay_learnings(self, days_since_validation: int = PRUNING_RETENTION_DAYS) -> int:
        """Decay confidence for learnings unvalidated for N days.

        Returns the number of affected rows.
        """
        self._ensure_connected()
        assert self._learnings is not None
        return await self._learnings.decay_learnings(days_since_validation)

    async def delete_learning(self, learning_id: int) -> None:
        """Delete a learning by ID."""
        self._ensure_connected()
        assert self._learnings is not None
        await self._learnings.delete_learning(learning_id)

    async def get_learning(self, learning_id: int) -> dict[str, Any] | None:
        """Retrieve a single learning by ID."""
        self._ensure_connected()
        assert self._learnings is not None
        return await self._learnings.get_learning(learning_id)

    # ------------------------------------------------------------------
    # Token usage aggregation (REQ-10.3)
    # ------------------------------------------------------------------

    async def get_token_summary(self) -> dict[str, Any]:
        """Aggregate token usage across all agents.

        Returns a dict with total_input, total_output, agent_count,
        and task_count.
        """
        self._ensure_connected()
        assert self._learnings is not None
        return await self._learnings.get_token_summary()

    # ------------------------------------------------------------------
    # Questions (REQ-15.1)
    # ------------------------------------------------------------------

    async def insert_question(self, record: QuestionRecord) -> None:
        """Insert a new question into the escalation queue."""
        self._ensure_connected()
        assert self._questions is not None
        await self._questions.insert_question(record)

    async def list_questions(self, answered: bool | None = None) -> list[dict[str, Any]]:
        """List questions, optionally filtered by answered status."""
        self._ensure_connected()
        assert self._questions is not None
        return await self._questions.list_questions(answered)

    async def get_question(self, question_id: str) -> dict[str, Any] | None:
        """Retrieve a single question by ID."""
        self._ensure_connected()
        assert self._questions is not None
        return await self._questions.get_question(question_id)

    async def answer_question(self, question_id: str, answer: str) -> None:
        """Mark a question as answered and store the response."""
        self._ensure_connected()
        assert self._questions is not None
        await self._questions.answer_question(question_id, answer)

    # ------------------------------------------------------------------
    # Checkpoints (REQ-07.2)
    # ------------------------------------------------------------------

    async def save_checkpoint(self, agent_id: str, task_id: str | None, state_json: str) -> None:
        """Persist an agent checkpoint."""
        self._ensure_connected()
        assert self._checkpoints is not None
        await self._checkpoints.save_checkpoint(agent_id, task_id, state_json)

    async def load_checkpoint(self, agent_id: str) -> dict[str, Any] | None:
        """Load the most recent checkpoint for an agent.

        Returns a dict with keys: agent_id, task_id, state_json, created_at;
        or None if no checkpoint exists.
        """
        self._ensure_connected()
        assert self._checkpoints is not None
        return await self._checkpoints.load_checkpoint(agent_id)

    # ------------------------------------------------------------------
    # Memories (REQ-07.5, REQ-07.6, REQ-07.7)
    # ------------------------------------------------------------------

    async def add_memory(self, summary: str, content: str, category: str) -> str:
        """Add a new memory entry. Returns the generated ID."""
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories.add_memory(summary, content, category)

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Retrieve a single memory by ID."""
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories.get_memory(memory_id)

    async def list_memory_summaries(self, limit: int = DEFAULT_MEMORY_LIST_LIMIT) -> list[dict[str, Any]]:
        """List memory summaries ordered by last_verified descending.

        Returns list of dicts with keys: id, summary, verified.
        """
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories.list_memory_summaries(limit)

    async def verify_memory(self, memory_id: str) -> None:
        """Mark a memory as verified against current state."""
        self._ensure_connected()
        assert self._memories is not None
        await self._memories.verify_memory(memory_id)

    async def consolidate_memories(self, stale_days: int = PRUNING_RETENTION_DAYS) -> int:
        """Remove stale unverified memories and merge duplicates.

        Returns count of deleted rows.
        """
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories.consolidate_memories(stale_days)

    async def _remove_stale_memories(self, stale_days: int) -> int:
        """Delete unverified memories older than stale_days."""
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories._remove_stale_memories(stale_days)

    async def _dedup_memories(self) -> int:
        """Merge duplicate summaries: keep most recent, delete the rest."""
        self._ensure_connected()
        assert self._memories is not None
        return await self._memories._dedup_memories()

    # ------------------------------------------------------------------
    # Eval Results (REQ-16.5)
    # ------------------------------------------------------------------

    async def store_eval_result(self, result_data: dict[str, Any]) -> None:
        """Persist an eval result.

        Expects keys: task_name, model, config_hash, task_completed,
        duration_seconds, input_tokens, output_tokens, tool_calls,
        turns, error, timestamp.
        """
        self._ensure_connected()
        assert self._db is not None
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
        self, task_name: str | None = None, limit: int = DEFAULT_QUERY_LIMIT
    ) -> list[dict[str, Any]]:
        """List eval results, most recent first, optionally by task_name."""
        self._ensure_connected()
        assert self._db is not None
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

    async def _get_tables(self) -> list[str]:
        """Return list of table names (used in tests)."""
        self._ensure_connected()
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
