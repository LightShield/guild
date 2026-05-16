"""Database query helpers for the Guild CLI.

All ``_fetch_*`` style functions that read from Storage and return
data for CLI display are collected here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from guild.config.loader import DB_FILENAME

if TYPE_CHECKING:
    from pathlib import Path

    from guild.escalation.queue import PendingQuestion

__all__ = [
    "answer_pending_question",
    "approve_all_questions",
    "approve_learning",
    "approve_selected_questions",
    "decay_learnings",
    "fetch_audit",
    "fetch_decisions",
    "fetch_learnings",
    "fetch_pending_questions",
    "fetch_task_history",
    "fetch_task_messages",
    "fetch_token_summary",
    "reject_learning",
]


async def fetch_audit(db_path: Path, limit: int) -> list[dict[str, Any]]:
    """Fetch audit log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        return await store.list_audit(limit=limit)


async def fetch_decisions(
    db_path: Path,
    task_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch decision log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        return await store.list_decisions(task_id=task_id, limit=limit)


async def fetch_task_history(db_path: Path, limit: int, status: str | None) -> list[dict[str, Any]]:
    """Fetch task history from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        tasks = await store.list_tasks(status=status)
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks[:limit]


async def fetch_token_summary(db_path: Path) -> dict[str, Any] | None:
    """Fetch token usage summary from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return None

    async with Storage(db_path) as store:
        return await store.get_token_summary()


async def fetch_task_messages(guild_dir: Path, task_id: str) -> list[dict[str, Any]]:
    """Fetch messages associated with a task's agent."""
    from guild.storage.sqlite import Storage

    db_path = guild_dir / DB_FILENAME
    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        task = await store.get_task(task_id)
        if task is None:
            return []

        agent_id = task.get("assigned_agent")
        if not agent_id:  # pragma: no cover — defensive guard for unassigned task
            return []

        return await store.get_messages(agent_id)  # pragma: no cover — requires task with messages


async def fetch_learnings(
    db_path: Path,
    category: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch learnings from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        return await store.list_learnings(category=category, limit=limit)


async def approve_learning(db_path: Path, learning_id: int) -> None:
    """Validate (approve) a learning, boosting its confidence."""
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        await store.validate_learning(learning_id)


async def reject_learning(db_path: Path, learning_id: int) -> None:
    """Delete a rejected learning."""
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        await store.delete_learning(learning_id)


async def decay_learnings(db_path: Path) -> int:
    """Run decay on old unvalidated learnings."""
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        return await store.decay_learnings()


# ------------------------------------------------------------------
# Escalation helpers (REQ-15.1)
# ------------------------------------------------------------------


async def fetch_pending_questions(db_path: Path) -> list[PendingQuestion]:
    """Fetch pending escalation questions from the database."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    async with Storage(db_path) as store:
        queue = QuestionQueue(store)
        return await queue.get_pending()


async def answer_pending_question(db_path: Path, question_id: str, response: str) -> None:
    """Answer a pending escalation question."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        queue = QuestionQueue(store)
        await queue.answer_question(question_id, response)


async def approve_all_questions(db_path: Path) -> int:
    """Approve all pending questions with a default 'approved' answer.

    Returns the number of questions approved.
    """
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        queue = QuestionQueue(store)
        pending = await queue.get_pending()
        answers = {q.id: "approved" for q in pending}
        return await queue.batch_answer(answers)


async def approve_selected_questions(db_path: Path, question_ids: list[str]) -> int:
    """Approve specific questions by ID with a default 'approved' answer.

    Returns the number of questions approved.
    """
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    async with Storage(db_path) as store:
        queue = QuestionQueue(store)
        answers = dict.fromkeys(question_ids, "approved")
        return await queue.batch_answer(answers)
