"""Asynchronous question queue for human-in-the-loop escalation (REQ-15.1).

Agents post questions here when they need human input. The queue persists
in SQLite and supports priority ordering and batch answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.storage.sqlite import Storage

__all__ = ["PendingQuestion", "QuestionPriority", "QuestionQueue"]

logger = get_logger(__name__)

_PRIORITY_ORDER = {"blocking": 0, "high": 1, "normal": 2, "low": 3}


class QuestionPriority(str, Enum):
    """Priority levels for escalation questions."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    BLOCKING = "blocking"


@dataclass
class PendingQuestion:
    """A question posted by an agent awaiting human response."""

    id: str
    task_id: str | None
    agent_id: str | None
    question: str
    context: str
    priority: QuestionPriority = QuestionPriority.NORMAL
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    answered: bool = False
    answer: str | None = None


class QuestionQueue:
    """Async question queue for human-in-the-loop escalation (REQ-15.1)."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def post_question(
        self,
        question: str,
        context: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        priority: QuestionPriority = QuestionPriority.NORMAL,
    ) -> str:
        """Post a question to the queue. Returns question ID."""
        question_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self._storage.insert_question(
            question_id=question_id,
            task_id=task_id,
            agent_id=agent_id,
            question=question,
            context=context,
            priority=priority.value,
            created_at=now,
        )
        logger.info("Question posted: %s (priority=%s)", question_id, priority.value)
        return question_id

    async def get_pending(self) -> list[PendingQuestion]:
        """Get all unanswered questions, highest priority first."""
        rows = await self._storage.list_questions(answered=False)
        questions = [self._row_to_question(row) for row in rows]
        questions.sort(key=lambda q: _PRIORITY_ORDER.get(q.priority.value, 2))
        return questions

    async def answer_question(self, question_id: str, answer: str) -> None:
        """Provide an answer to a pending question."""
        await self._storage.answer_question(question_id, answer)
        logger.info("Question answered: %s", question_id)

    async def get_answer(self, question_id: str) -> str | None:
        """Check if a question has been answered. Returns answer or None."""
        row = await self._storage.get_question(question_id)
        if row is None:
            return None
        if not row["answered"]:
            return None
        answer: str | None = row["answer"]
        return answer

    async def batch_answer(self, answers: dict[str, str]) -> int:
        """Answer multiple questions at once. Returns count answered."""
        count = 0
        for question_id, answer in answers.items():
            await self._storage.answer_question(question_id, answer)
            count += 1
        logger.info("Batch answered %d question(s)", count)
        return count

    @staticmethod
    def _row_to_question(row: dict[str, Any]) -> PendingQuestion:
        """Convert a database row dict to a PendingQuestion."""
        return PendingQuestion(
            id=row["id"],
            task_id=row.get("task_id"),
            agent_id=row.get("agent_id"),
            question=row["question"],
            context=row["context"],
            priority=QuestionPriority(row.get("priority", "normal")),
            created_at=row.get("created_at", ""),
            answered=bool(row.get("answered", 0)),
            answer=row.get("answer"),
        )
