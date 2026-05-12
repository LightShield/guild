"""Tests for knowledge/memory.py — skeptical memory system (REQ-07.5, 07.6, 07.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.knowledge.memory import MemoryIndex
from guild.storage.sqlite import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance with memories table."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


@pytest.fixture
def memory_index(storage: Storage) -> MemoryIndex:
    """Create a MemoryIndex bound to the test storage."""
    return MemoryIndex(storage)


# ------------------------------------------------------------------
# REQ-07.5: Skeptical memory — verify before acting
# ------------------------------------------------------------------


@pytest.mark.unit
class TestSkepticalMemory:
    """Tests for memory verification."""

    async def test_verify_marks_entry_verified(
        self, memory_index: MemoryIndex, storage: Storage
    ) -> None:
        """verify() sets verified=True and records last_verified timestamp."""
        mid = await memory_index.add(
            summary="Python 3.11 is the minimum version",
            content="The project requires Python 3.11+",
            category="fact",
        )

        await memory_index.verify(mid)

        entry = await memory_index.fetch_detail(mid)
        assert entry is not None
        assert entry.verified is True
        assert entry.last_verified is not None

    async def test_unverified_entries_flagged(self, memory_index: MemoryIndex) -> None:
        """Unverified entries appear with [unverified] prefix in index."""
        await memory_index.add(
            summary="Uses SQLite for storage",
            content="All state stored in SQLite with WAL mode",
            category="codebase",
        )

        index = await memory_index.get_index()

        assert len(index) == 1
        assert "[unverified]" in index[0]
        assert "Uses SQLite for storage" in index[0]


# ------------------------------------------------------------------
# REQ-07.6: Lightweight memory index, details on demand
# ------------------------------------------------------------------


@pytest.mark.unit
class TestLightweightIndex:
    """Tests for lightweight index with on-demand detail fetching."""

    async def test_get_index_returns_summaries_only(self, memory_index: MemoryIndex) -> None:
        """get_index() returns summary strings, not full content."""
        await memory_index.add(
            summary="Short summary",
            content="This is a much longer content body with details.",
            category="fact",
        )

        index = await memory_index.get_index()

        assert len(index) == 1
        assert "Short summary" in index[0]
        # Full content should NOT be in the index
        assert "much longer content body" not in index[0]

    async def test_fetch_detail_returns_full_content(self, memory_index: MemoryIndex) -> None:
        """fetch_detail() returns the complete MemoryEntry with content."""
        mid = await memory_index.add(
            summary="Short summary",
            content="Full detailed content here.",
            category="decision",
        )

        entry = await memory_index.fetch_detail(mid)

        assert entry is not None
        assert entry.summary == "Short summary"
        assert entry.content == "Full detailed content here."
        assert entry.category == "decision"

    async def test_index_under_200_lines(self, memory_index: MemoryIndex) -> None:
        """Index never exceeds 200 entries regardless of memory count."""
        # Add 250 entries
        for i in range(250):
            await memory_index.add(
                summary=f"Memory entry number {i}",
                content=f"Content for entry {i}",
                category="fact",
            )

        index = await memory_index.get_index()

        assert len(index) <= 200


# ------------------------------------------------------------------
# REQ-07.7: Memory consolidation during idle time
# ------------------------------------------------------------------


@pytest.mark.unit
class TestMemoryConsolidation:
    """Tests for memory consolidation."""

    async def test_consolidate_removes_stale_entries(
        self, memory_index: MemoryIndex, storage: Storage
    ) -> None:
        """Entries unverified for 30+ days are removed during consolidation."""
        # Manually insert a stale entry with old created_at
        old_date = (datetime.now(UTC) - timedelta(days=35)).isoformat()
        assert storage._db is not None
        await storage._db.execute(
            "INSERT INTO memories"
            " (id, summary, content, category, verified, last_verified, created_at)"
            " VALUES (?, ?, ?, ?, 0, NULL, ?)",
            ("stale-1", "Old memory", "Old content", "fact", old_date),
        )
        await storage._db.commit()

        # Add a fresh entry
        fresh_id = await memory_index.add(
            summary="Fresh memory",
            content="New content",
            category="fact",
        )

        changes = await memory_index.consolidate()

        assert changes >= 1
        # Stale entry should be gone
        stale = await memory_index.fetch_detail("stale-1")
        assert stale is None
        # Fresh entry should remain
        fresh = await memory_index.fetch_detail(fresh_id)
        assert fresh is not None

    async def test_consolidate_merges_duplicates(self, memory_index: MemoryIndex) -> None:
        """Duplicate summaries are merged (only one kept) during consolidation."""
        await memory_index.add(
            summary="Duplicate summary",
            content="First version content",
            category="fact",
        )
        await memory_index.add(
            summary="Duplicate summary",
            content="Second version content",
            category="fact",
        )

        # Both should exist before consolidation
        index_before = await memory_index.get_index()
        dup_count = sum(1 for e in index_before if "Duplicate summary" in e)
        assert dup_count == 2

        changes = await memory_index.consolidate()

        assert changes >= 1
        # Only one should remain
        index_after = await memory_index.get_index()
        dup_count_after = sum(1 for e in index_after if "Duplicate summary" in e)
        assert dup_count_after == 1


# ======================================================================
# Memory format_index_for_prompt (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestMemoryFormatIndex:
    """Tests for MemoryIndex.format_index_for_prompt."""

    def test_format_empty_index_returns_empty(self) -> None:
        """Empty index produces an empty string."""
        index = MemoryIndex.__new__(MemoryIndex)
        result = index.format_index_for_prompt([])
        assert result == ""

    def test_format_index_with_entries(self) -> None:
        """Non-empty index produces header and bullet list."""
        index = MemoryIndex.__new__(MemoryIndex)
        result = index.format_index_for_prompt(["Entry one", "Entry two"])
        assert "## Agent Memory Index" in result
        assert "- Entry one" in result
        assert "- Entry two" in result
