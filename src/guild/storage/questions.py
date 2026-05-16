"""Questions (escalation queue) operations for Guild storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiosqlite
from logger_python import get_logger

__all__ = ["QuestionOps", "QuestionRecord"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


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


class QuestionOps:
    """Question (escalation queue) persistence operations."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        """Initialize with a database connection."""
        self._db = db

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
        cursor = await self._db.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def answer_question(self, question_id: str, answer: str) -> None:
        """Mark a question as answered and store the response."""
        await self._db.execute(
            "UPDATE questions SET answered = 1, answer = ?, answered_at = ?" " WHERE id = ?",
            (answer, _now(), question_id),
        )
        await self._db.commit()
