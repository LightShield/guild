"""Learnings and token usage operations for Guild storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from guild.config.constants import (
    CONFIDENCE_DECAY_DECREMENT,
    CONFIDENCE_INVALIDATE_DECREMENT,
    CONFIDENCE_VALIDATE_INCREMENT,
    DEFAULT_QUERY_LIMIT,
    PRUNING_RETENTION_DAYS,
)
from guild.storage.connection import DBConnection
from logger_python import get_logger

__all__ = ["LearningOps", "LearningRecord"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


@dataclass
class LearningRecord:
    """Record for a new learning entry."""

    category: str
    content: str
    confidence: float = 0.3
    scope: str | None = None
    source_task_id: str | None = None


class LearningOps:
    """Learning and token usage persistence operations."""

    def __init__(self, db: DBConnection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def add_learning(self, record: LearningRecord) -> int:
        """Insert a new learning and return its ID."""
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
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[dict[str, Any]]:
        """List learnings filtered by confidence, category, and scope."""
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
        await self._db.execute(
            "UPDATE learnings SET confidence = MAX(confidence - ?, 0.0) WHERE id = ?",
            (CONFIDENCE_INVALIDATE_DECREMENT, learning_id),
        )
        await self._db.commit()

    async def decay_learnings(self, days_since_validation: int = PRUNING_RETENTION_DAYS) -> int:
        """Decay confidence for learnings unvalidated for N days.

        Returns the number of affected rows.
        """
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
        await self._db.execute("DELETE FROM learnings WHERE id = ?", (learning_id,))
        await self._db.commit()

    async def get_learning(self, learning_id: int) -> dict[str, Any] | None:
        """Retrieve a single learning by ID."""
        cursor = await self._db.execute("SELECT * FROM learnings WHERE id = ?", (learning_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def get_token_summary(self) -> dict[str, Any]:
        """Aggregate token usage across all agents.

        Returns a dict with total_input, total_output, agent_count,
        and task_count.
        """
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
