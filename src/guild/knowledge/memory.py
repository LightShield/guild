"""Skeptical memory system with lightweight index (REQ-07.5, REQ-07.6, REQ-07.7).

Provides a memory index that is always loaded (summaries only), with full
content fetched on demand. Memories are verified against actual state before
being trusted, and consolidated during idle time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
        rows = await self._storage.list_memory_summaries(limit=_MAX_INDEX_LINES)
        results: list[str] = []
        for row in rows:
            prefix = "" if row["verified"] else "[unverified] "
            results.append(f"{prefix}{row['summary']}")
        return results

    async def fetch_detail(self, memory_id: str) -> MemoryEntry | None:
        """Fetch full content of a memory entry by ID."""
        row = await self._storage.get_memory(memory_id)
        if row is None:
            return None
        return MemoryEntry(
            id=row["id"],
            summary=row["summary"],
            content=row["content"],
            category=row["category"],
            verified=bool(row["verified"]),
            last_verified=row["last_verified"],
        )

    async def add(self, summary: str, content: str, category: str) -> str:
        """Add a new memory entry. Returns the generated ID."""
        return await self._storage.add_memory(summary, content, category)

    async def verify(self, memory_id: str) -> None:
        """Mark a memory as verified against current state."""
        await self._storage.verify_memory(memory_id)

    async def consolidate(self) -> int:
        """Merge/deduplicate/clean stale entries. Returns count of changes.

        Actions performed:
        - Remove entries not verified in 30+ days
        - Merge entries with identical summaries (keep most recent)
        """
        changes = await self._storage.consolidate_memories(stale_days=_STALE_DAYS)
        logger.info("Memory consolidation: %d changes", changes)
        return changes

    def format_index_for_prompt(self, index: list[str]) -> str:
        """Format the index for injection into system prompt."""
        if not index:
            return ""
        header = "## Agent Memory Index\n"
        lines = [f"- {entry}" for entry in index[:_MAX_INDEX_LINES]]
        return header + "\n".join(lines)
