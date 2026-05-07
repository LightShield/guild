"""Tests for escalation/queue.py — async question queue (REQ-15.1, REQ-15.3, REQ-15.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.escalation.queue import QuestionPriority, QuestionQueue
from guild.storage.sqlite import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
async def queue(storage: Storage) -> QuestionQueue:
    """Create a QuestionQueue backed by test storage."""
    return QuestionQueue(storage)


@pytest.mark.unit
@pytest.mark.req("REQ-15.1")
class TestPostQuestion:
    """Posting questions to the escalation queue."""

    async def test_post_question_stores_in_queue(self, queue: QuestionQueue) -> None:
        """A posted question appears in the pending list."""
        qid = await queue.post_question(
            question="How should I handle this edge case?",
            context="Tried approaches A and B, both failed.",
            task_id="task-1",
            agent_id="agent-1",
        )
        assert qid  # non-empty ID returned
        pending = await queue.get_pending()
        assert len(pending) == 1
        assert pending[0].id == qid
        assert pending[0].question == "How should I handle this edge case?"

    async def test_get_pending_returns_unanswered(self, queue: QuestionQueue) -> None:
        """Only unanswered questions appear in pending list."""
        qid1 = await queue.post_question(
            question="Question 1",
            context="Context 1",
        )
        qid2 = await queue.post_question(
            question="Question 2",
            context="Context 2",
        )
        await queue.answer_question(qid1, "Answer 1")

        pending = await queue.get_pending()
        assert len(pending) == 1
        assert pending[0].id == qid2

    async def test_answer_marks_as_answered(self, queue: QuestionQueue) -> None:
        """Answering a question removes it from pending."""
        qid = await queue.post_question(
            question="Need help",
            context="Stuck on X",
        )
        await queue.answer_question(qid, "Do Y instead")

        pending = await queue.get_pending()
        assert len(pending) == 0

    async def test_get_answer_returns_none_when_unanswered(
        self, queue: QuestionQueue
    ) -> None:
        """get_answer returns None for unanswered questions."""
        qid = await queue.post_question(
            question="Pending question",
            context="Some context",
        )
        answer = await queue.get_answer(qid)
        assert answer is None

    async def test_get_answer_returns_answer_when_answered(
        self, queue: QuestionQueue
    ) -> None:
        """get_answer returns the answer text after answering."""
        qid = await queue.post_question(
            question="What should I do?",
            context="Tried everything",
        )
        await queue.answer_question(qid, "Try approach C")

        answer = await queue.get_answer(qid)
        assert answer == "Try approach C"


@pytest.mark.unit
@pytest.mark.req("REQ-15.3")
class TestEscalationContext:
    """Escalation context preservation."""

    async def test_question_includes_context(self, queue: QuestionQueue) -> None:
        """Posted question retains its escalation context."""
        context_text = (
            "Attempted: 1) grep for pattern, 2) read config file, "
            "3) asked other agent. All returned empty results."
        )
        await queue.post_question(
            question="Where is the config stored?",
            context=context_text,
            task_id="task-42",
            agent_id="researcher-1",
        )
        pending = await queue.get_pending()
        q = pending[0]
        assert q.context == context_text
        assert q.task_id == "task-42"
        assert q.agent_id == "researcher-1"


@pytest.mark.unit
@pytest.mark.req("REQ-15.4")
class TestBatchAnswer:
    """Batch approval of multiple questions."""

    async def test_batch_answer_multiple_questions(
        self, queue: QuestionQueue
    ) -> None:
        """batch_answer answers multiple questions at once."""
        qid1 = await queue.post_question(question="Q1", context="C1")
        qid2 = await queue.post_question(question="Q2", context="C2")
        qid3 = await queue.post_question(question="Q3", context="C3")

        await queue.batch_answer({qid1: "A1", qid2: "A2"})

        assert await queue.get_answer(qid1) == "A1"
        assert await queue.get_answer(qid2) == "A2"
        assert await queue.get_answer(qid3) is None

    async def test_batch_answer_returns_count(self, queue: QuestionQueue) -> None:
        """batch_answer returns the number of questions answered."""
        qid1 = await queue.post_question(question="Q1", context="C1")
        qid2 = await queue.post_question(question="Q2", context="C2")

        count = await queue.batch_answer({qid1: "A1", qid2: "A2"})
        assert count == 2


@pytest.mark.unit
@pytest.mark.req("REQ-15.1")
class TestPriorityOrdering:
    """Questions are returned in priority order."""

    async def test_pending_ordered_by_priority(
        self, queue: QuestionQueue
    ) -> None:
        """get_pending returns highest priority first."""
        await queue.post_question(
            question="Low", context="C", priority=QuestionPriority.LOW
        )
        await queue.post_question(
            question="Blocking", context="C", priority=QuestionPriority.BLOCKING
        )
        await queue.post_question(
            question="Normal", context="C", priority=QuestionPriority.NORMAL
        )

        pending = await queue.get_pending()
        assert pending[0].question == "Blocking"
        assert pending[1].question == "Normal"
        assert pending[2].question == "Low"
