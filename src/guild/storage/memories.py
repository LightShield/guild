"""Memory operations for Guild storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from guild.storage.connection import DBConnection
from logger_python import get_logger

from guild.config.constants import (
    DEFAULT_MEMORY_LIST_LIMIT,
    MEMORY_SUMMARY_MAX_CHARS,
    PRUNING_RETENTION_DAYS,
)

__all__ = ["MemoryOps"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


class MemoryOps:
    """Memory persistence operations."""

    def __init__(self, db: DBConnection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def add_memory(self, summary: str, content: str, category: str) -> str:
        """Add a new memory entry. Returns the generated ID."""
        import uuid

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
        cursor = await self._db.execute(
            "SELECT id, summary, content, category, verified, last_verified, created_at"
            " FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_memory_summaries(
        self, limit: int = DEFAULT_MEMORY_LIST_LIMIT
    ) -> list[dict[str, Any]]:
        """List memory summaries ordered by last_verified descending.

        Returns list of dicts with keys: id, summary, verified.
        """
        cursor = await self._db.execute(
            "SELECT id, summary, verified FROM memories"
            " ORDER BY CASE WHEN last_verified IS NULL THEN 1 ELSE 0 END,"
            " last_verified DESC"
            " LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def verify_memory(self, memory_id: str) -> None:
        """Mark a memory as verified against current state."""
        await self._db.execute(
            "UPDATE memories SET verified = 1, last_verified = ? WHERE id = ?",
            (_now(), memory_id),
        )
        await self._db.commit()

    async def consolidate_memories(self, stale_days: int = PRUNING_RETENTION_DAYS) -> int:
        """Remove stale unverified memories and merge duplicates.

        Returns count of deleted rows.
        """
        changes = await self._remove_stale_memories(stale_days)
        changes += await self._dedup_memories()
        await self._db.commit()
        return changes

    async def _remove_stale_memories(self, stale_days: int) -> int:
        """Delete unverified memories older than stale_days."""
        from datetime import timedelta

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
