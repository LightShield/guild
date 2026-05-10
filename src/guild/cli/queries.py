"""Database query helpers for the Guild CLI.

All ``_fetch_*`` style functions that read from Storage and return
data for CLI display are collected here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "answer_pending_question",
    "approve_learning",
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


async def fetch_audit(db_path: Path, limit: int) -> list[dict]:
    """Fetch audit log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_audit(limit=limit)
    await store.close()
    return entries


async def fetch_decisions(
    db_path: Path,
    task_id: str | None,
    limit: int,
) -> list[dict]:
    """Fetch decision log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_decisions(task_id=task_id, limit=limit)
    await store.close()
    return entries


async def fetch_task_history(db_path: Path, limit: int, status: str | None) -> list[dict]:
    """Fetch task history from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()
    tasks = await store.list_tasks(status=status)
    await store.close()
    # Return most recent first, capped at limit
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks[:limit]


async def fetch_token_summary(db_path: Path) -> dict | None:
    """Fetch token usage summary from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return None

    store = Storage(db_path)
    await store.connect()
    summary = await store.get_token_summary()
    await store.close()
    return summary


async def fetch_task_messages(guild_dir: Path, task_id: str) -> list[dict]:
    """Fetch messages associated with a task's agent."""
    from guild.storage.sqlite import Storage

    db_path = guild_dir / "guild.db"
    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()

    # Check if the task exists and has an assigned agent
    task = await store.get_task(task_id)
    if task is None:
        await store.close()
        return []

    agent_id = task.get("assigned_agent")
    if not agent_id:  # pragma: no cover — defensive guard for unassigned task
        await store.close()
        return []

    messages = await store.get_messages(agent_id)  # pragma: no cover — requires task with messages
    await store.close()
    return messages


# ------------------------------------------------------------------
# Learnings helpers
# ------------------------------------------------------------------


async def fetch_learnings(
    db_path: Path,
    category: str | None,
    limit: int,
) -> list[dict]:
    """Fetch learnings from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_learnings(category=category, limit=limit)
    await store.close()
    return entries


async def approve_learning(db_path: Path, learning_id: int) -> None:
    """Validate (approve) a learning, boosting its confidence."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    await store.validate_learning(learning_id)
    await store.close()


async def reject_learning(db_path: Path, learning_id: int) -> None:
    """Delete a rejected learning."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    await store.delete_learning(learning_id)
    await store.close()


async def decay_learnings(db_path: Path) -> int:
    """Run decay on old unvalidated learnings."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    count = await store.decay_learnings()
    await store.close()
    return count


# ------------------------------------------------------------------
# Escalation helpers (REQ-15.1)
# ------------------------------------------------------------------


async def fetch_pending_questions(db_path: Path) -> list:
    """Fetch pending escalation questions from the database."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    if not db_path.exists():  # pragma: no cover — defensive guard for missing db
        return []

    store = Storage(db_path)
    await store.connect()
    queue = QuestionQueue(store)
    pending = await queue.get_pending()
    await store.close()
    return pending


async def answer_pending_question(db_path: Path, question_id: str, response: str) -> None:
    """Answer a pending escalation question."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    queue = QuestionQueue(store)
    await queue.answer_question(question_id, response)
    await store.close()
