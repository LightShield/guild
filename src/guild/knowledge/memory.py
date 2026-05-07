"""Skeptical memory system with lightweight index (REQ-07.5, REQ-07.6, REQ-07.7).

Provides a memory index that is always loaded (summaries only), with full
content fetched on demand. Memories are verified against actual state before
being trusted, and consolidated during idle time.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guild.storage.sqlite import Storage

__all__ = ["MemoryEntry", "MemoryIndex"]

logger = logging.getLogger(__name__)

_STALE_DAYS = 30
_MAX_INDEX_LINES = 200


@dataclass
class MemoryEntry:
    """A single memory with summary index and full content."""

    id: str
    summary: str  # one-line index entry (<200 chars)
    content: str  # full content (fetched on demand)
    category: str  # "fact", "preference", "codebase", "decision"
    verified: bool = False
    last_verified: str | None = None


class MemoryIndex:
    """Lightweight memory system -- index always loaded, details on demand.

    The index (summaries) is always available for prompt injection.
    Full content is fetched only when needed.  Entries are skeptically
    treated: unverified entries are flagged, and consolidation removes
    stale or duplicate entries during idle time.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def get_index(self) -> list[str]:
        """Get all memory summaries (capped at MAX_INDEX_LINES).

        Returns a list of summary strings, one per memory entry.
        """
        assert self._storage._db is not None
        cursor = await self._storage._db.execute(
            "SELECT id, summary, verified FROM memories"
            " ORDER BY last_verified DESC NULLS LAST"
            f" LIMIT {_MAX_INDEX_LINES}"
        )
        rows = await cursor.fetchall()
        results: list[str] = []
        for row in rows:
            prefix = "" if row[2] else "[unverified] "
            results.append(f"{prefix}{row[1]}")
        return results

    async def fetch_detail(self, memory_id: str) -> MemoryEntry | None:
        """Fetch full content of a memory entry by ID."""
        assert self._storage._db is not None
        cursor = await self._storage._db.execute(
            "SELECT id, summary, content, category, verified, last_verified"
            " FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return MemoryEntry(
            id=row[0],
            summary=row[1],
            content=row[2],
            category=row[3],
            verified=bool(row[4]),
            last_verified=row[5],
        )

    async def add(self, summary: str, content: str, category: str) -> str:
        """Add a new memory entry. Returns the generated ID."""
        assert self._storage._db is not None
        memory_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self._storage._db.execute(
            "INSERT INTO memories"
            " (id, summary, content, category, verified, last_verified, created_at)"
            " VALUES (?, ?, ?, ?, 0, NULL, ?)",
            (memory_id, summary[:200], content, category, now),
        )
        await self._storage._db.commit()
        return memory_id

    async def verify(self, memory_id: str) -> None:
        """Mark a memory as verified against current state."""
        assert self._storage._db is not None
        now = datetime.now(UTC).isoformat()
        await self._storage._db.execute(
            "UPDATE memories SET verified = 1, last_verified = ? WHERE id = ?",
            (now, memory_id),
        )
        await self._storage._db.commit()

    async def consolidate(self) -> int:
        """Merge/deduplicate/clean stale entries. Returns count of changes.

        Actions performed:
        - Remove entries not verified in 30+ days
        - Merge entries with identical summaries (keep most recent)
        """
        assert self._storage._db is not None
        changes = 0

        # Remove stale unverified entries older than 30 days
        cutoff = (datetime.now(UTC) - timedelta(days=_STALE_DAYS)).isoformat()
        cursor = await self._storage._db.execute(
            "DELETE FROM memories"
            " WHERE verified = 0"
            " AND (last_verified IS NULL OR last_verified < ?)"
            " AND created_at < ?",
            (cutoff, cutoff),
        )
        changes += cursor.rowcount

        # Merge duplicate summaries: keep the most recently verified
        dup_cursor = await self._storage._db.execute(
            "SELECT summary, COUNT(*) as cnt FROM memories" " GROUP BY summary HAVING cnt > 1"
        )
        duplicates = await dup_cursor.fetchall()
        for dup_row in duplicates:
            summary = dup_row[0]
            # Keep the most recently created entry, delete the rest
            entries_cursor = await self._storage._db.execute(
                "SELECT id FROM memories WHERE summary = ?" " ORDER BY created_at DESC",
                (summary,),
            )
            entries = await entries_cursor.fetchall()
            ids_to_delete = [e[0] for e in entries[1:]]
            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                del_cursor = await self._storage._db.execute(
                    f"DELETE FROM memories WHERE id IN ({placeholders})",  # noqa: S608
                    ids_to_delete,
                )
                changes += del_cursor.rowcount

        await self._storage._db.commit()
        logger.info("Memory consolidation: %d changes", changes)
        return changes

    def format_index_for_prompt(self, index: list[str]) -> str:
        """Format the index for injection into system prompt."""
        if not index:
            return ""
        header = "## Agent Memory Index\n"
        lines = [f"- {entry}" for entry in index[:_MAX_INDEX_LINES]]
        return header + "\n".join(lines)
