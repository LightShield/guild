"""E2E acceptance tests for context management and learning loop.

Exercises the full component stack from Storage through domain logic.
Only the LLM provider (external I/O) is mocked.

Requirements covered:
  REQ-07.1  Persistent context across sessions
  REQ-07.2  Checkpoint and resume
  REQ-07.3  Shared knowledge between agents
  REQ-07.4  Multi-tier context compression
  REQ-07.5  Skeptical memory (verify before acting)
  REQ-07.6  Lightweight memory index
  REQ-07.7  Memory consolidation
  REQ-07.8  Context resets with handoff
  REQ-07.10 Static/dynamic prompt separation
  REQ-09.2  Knowledge categories
  REQ-09.3  Confidence scoring
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from guild.agent.checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from guild.agent.context import (
    CHARS_PER_TOKEN,
    MIN_CONTENT_LEN,
    TRUNCATION_MARKER,
    ContextManager,
)
from guild.agent.learning import extract_learnings, format_learnings_for_injection
from guild.agent.message import Message
from guild.config.constants import (
    CONFIDENCE_DECAY_DECREMENT,
    CONFIDENCE_INVALIDATE_DECREMENT,
    CONFIDENCE_VALIDATE_INCREMENT,
    MIN_INJECTION_CONFIDENCE,
)
from guild.knowledge.memory import MemoryIndex
from guild.orchestration.bus import SharedContext
from guild.provider.base import LLMResponse
from guild.storage.sqlite import Storage

pytestmark = pytest.mark.e2e


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
async def storage(tmp_path: Path) -> Storage:
    """Real SQLite storage, connected and torn down after each test."""
    store = Storage(tmp_path / "guild.db")
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


@pytest.fixture()
def ctx() -> ContextManager:
    """Real ContextManager with default settings."""
    return ContextManager()


@pytest.fixture()
def memory_index(storage: Storage) -> MemoryIndex:
    """Real MemoryIndex backed by real storage."""
    return MemoryIndex(storage)


# ------------------------------------------------------------------
# REQ-07.1: Persistent context across sessions
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.1")
class TestPersistentContext:
    """Messages stored in one session are retrievable in a subsequent session."""

    async def test_messages_persist_across_sessions(self, tmp_path: Path) -> None:
        """Append messages, close DB, reopen, and verify they survive."""
        db_path = tmp_path / "persist.db"

        # Session 1 -- write messages
        store1 = Storage(db_path)
        await store1.connect()
        await store1.register_agent("agent-1", "coder")
        await store1.append_message("agent-1", "system", "You are helpful.")
        await store1.append_message("agent-1", "user", "Fix the parser.")
        await store1.append_message("agent-1", "assistant", "On it.")
        await store1.close()

        # Session 2 -- read messages
        store2 = Storage(db_path)
        await store2.connect()
        messages = await store2.get_messages("agent-1")
        await store2.close()

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Fix the parser."
        assert messages[2]["role"] == "assistant"

    async def test_learnings_survive_restart(self, tmp_path: Path) -> None:
        """Learnings persisted in session 1 are available in session 2."""
        db_path = tmp_path / "learn_persist.db"

        store1 = Storage(db_path)
        await store1.connect()
        lid = await store1.add_learning(
            category="pattern",
            content="Use guard clauses",
            confidence=0.7,
        )
        await store1.close()

        store2 = Storage(db_path)
        await store2.connect()
        learning = await store2.get_learning(lid)
        await store2.close()

        assert learning is not None
        assert learning["content"] == "Use guard clauses"
        assert learning["confidence"] == pytest.approx(0.7)


# ------------------------------------------------------------------
# REQ-07.2: Checkpoint and resume
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.2")
class TestCheckpointResume:
    """Save agent state, shut down, reload, and continue from where we left off."""

    async def test_checkpoint_save_and_restore(self, storage: Storage) -> None:
        """Full round-trip: save checkpoint -> load checkpoint -> same state."""
        original = Checkpoint(
            agent_id="agent-ckpt",
            task_id="task-42",
            messages=[
                Message(role="system", content="You are a coder."),
                Message(role="user", content="Refactor module X."),
                Message(role="assistant", content="Starting refactor."),
            ],
            turn_number=5,
            total_input_tokens=2000,
            total_output_tokens=1500,
            total_tool_calls=8,
        )
        await save_checkpoint(storage, original)

        loaded = await load_checkpoint(storage, "agent-ckpt")

        assert loaded is not None
        assert loaded.agent_id == "agent-ckpt"
        assert loaded.task_id == "task-42"
        assert loaded.turn_number == 5
        assert loaded.total_input_tokens == 2000
        assert loaded.total_output_tokens == 1500
        assert loaded.total_tool_calls == 8
        assert len(loaded.messages) == 3
        assert loaded.messages[1].content == "Refactor module X."

    async def test_latest_checkpoint_wins(self, storage: Storage) -> None:
        """When multiple checkpoints exist, the most recent is loaded."""
        cp1 = Checkpoint(
            agent_id="agent-multi",
            task_id="t",
            messages=[Message(role="user", content="first")],
            turn_number=1,
            total_input_tokens=100,
            total_output_tokens=50,
            total_tool_calls=0,
        )
        cp2 = Checkpoint(
            agent_id="agent-multi",
            task_id="t",
            messages=[Message(role="user", content="second")],
            turn_number=10,
            total_input_tokens=900,
            total_output_tokens=400,
            total_tool_calls=7,
        )
        await save_checkpoint(storage, cp1)
        await save_checkpoint(storage, cp2)

        loaded = await load_checkpoint(storage, "agent-multi")
        assert loaded is not None
        assert loaded.turn_number == 10
        assert loaded.messages[0].content == "second"

    async def test_checkpoint_survives_db_reopen(self, tmp_path: Path) -> None:
        """Checkpoint written before close is available after reopen."""
        db_path = tmp_path / "ckpt_reopen.db"
        store1 = Storage(db_path)
        await store1.connect()
        cp = Checkpoint(
            agent_id="agent-reopen",
            task_id="t",
            messages=[Message(role="user", content="hello")],
            turn_number=3,
            total_input_tokens=50,
            total_output_tokens=25,
            total_tool_calls=1,
        )
        await save_checkpoint(store1, cp)
        await store1.close()

        store2 = Storage(db_path)
        await store2.connect()
        loaded = await load_checkpoint(store2, "agent-reopen")
        await store2.close()

        assert loaded is not None
        assert loaded.turn_number == 3


# ------------------------------------------------------------------
# REQ-07.3: Shared knowledge between agents
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.3")
class TestSharedKnowledge:
    """Agents share knowledge through the SharedContext store and Storage."""

    async def test_shared_context_between_agents(self) -> None:
        """Agent A writes to SharedContext, Agent B reads the same data."""
        shared = SharedContext()
        shared.put("project_style", {"indent": 4, "quotes": "double"}, agent_id="agent-a")

        data = shared.get("project_style")
        assert data is not None
        assert data["indent"] == 4
        assert data["quotes"] == "double"

    async def test_learnings_visible_across_agents(self, storage: Storage) -> None:
        """Learnings stored by agent A's task are available to agent B."""
        # Agent A's task stores a learning
        await storage.create_task("task-a", "Build API")
        await storage.update_task("task-a", assigned_agent="agent-a")
        lid = await storage.add_learning(
            category="pattern",
            content="Always validate request bodies",
            confidence=0.7,
            source_task_id="task-a",
        )

        # Agent B queries learnings before its own task
        learnings = await storage.list_learnings(min_confidence=0.5)
        assert any(l["content"] == "Always validate request bodies" for l in learnings)

        # Injection formatting works for agent B
        injection = format_learnings_for_injection(learnings)
        assert "Always validate request bodies" in injection

    async def test_shared_context_list_keys(self) -> None:
        """SharedContext.list_keys returns all stored keys."""
        shared = SharedContext()
        shared.put("k1", {"v": 1}, agent_id="a1")
        shared.put("k2", {"v": 2}, agent_id="a2")
        keys = shared.list_keys()
        assert set(keys) == {"k1", "k2"}


# ------------------------------------------------------------------
# REQ-07.4: Multi-tier context compression
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.4")
class TestContextCompression:
    """Compression reduces token count while preserving essential context."""

    def test_compression_reduces_tokens(self) -> None:
        """After compaction, token estimate is lower than before."""
        cm = ContextManager(max_tokens=200, preserve_recent=2, compact_threshold=0.5)
        messages = [Message(role="system", content="You are helpful.")]
        # Add enough tool messages to exceed the threshold
        for i in range(10):
            messages.append(Message(role="assistant", content=f"Calling tool {i}"))
            messages.append(Message(role="tool", content="x" * 400))

        before_tokens = cm.estimate_tokens(messages)
        assert cm.needs_compaction(messages)

        compacted = cm.compact(messages)
        after_tokens = cm.estimate_tokens(compacted)

        assert after_tokens < before_tokens

    def test_compression_preserves_message_count(self) -> None:
        """Compaction never drops messages, only shortens content."""
        cm = ContextManager(max_tokens=100, preserve_recent=2, compact_threshold=0.5)
        messages = [Message(role="system", content="sys")]
        for _ in range(8):
            messages.append(Message(role="assistant", content="do"))
            messages.append(Message(role="tool", content="y" * 500))

        compacted = cm.compact(messages)
        assert len(compacted) == len(messages)

    def test_system_prompt_never_truncated(self) -> None:
        """System prompt is protected from compaction regardless of size."""
        long_system = "You are an agent. " * 200
        cm = ContextManager(max_tokens=50, preserve_recent=2, compact_threshold=0.5)
        messages = [
            Message(role="system", content=long_system),
            Message(role="tool", content="r" * 600),
            Message(role="assistant", content="done"),
        ]
        compacted = cm.compact(messages)
        assert compacted[0].content == long_system


# ------------------------------------------------------------------
# REQ-07.5: Skeptical memory (verify before acting)
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.5")
class TestSkepticalMemory:
    """Memories are unverified until explicitly verified; index reflects status."""

    async def test_new_memory_is_unverified(self, memory_index: MemoryIndex) -> None:
        """Freshly added memory appears with [unverified] in index."""
        await memory_index.add(
            summary="Project uses Python 3.11",
            content="Minimum Python version is 3.11",
            category="fact",
        )
        index = await memory_index.get_index()
        assert len(index) == 1
        assert "[unverified]" in index[0]

    async def test_verified_memory_loses_prefix(self, memory_index: MemoryIndex) -> None:
        """After verification, the [unverified] prefix is removed."""
        mid = await memory_index.add(
            summary="Uses SQLite",
            content="Storage backed by SQLite with WAL",
            category="codebase",
        )
        await memory_index.verify(mid)

        index = await memory_index.get_index()
        assert len(index) == 1
        assert "[unverified]" not in index[0]
        assert "Uses SQLite" in index[0]

    async def test_verify_records_timestamp(
        self, memory_index: MemoryIndex, storage: Storage
    ) -> None:
        """verify() sets the last_verified timestamp."""
        mid = await memory_index.add(
            summary="Fact",
            content="Detail",
            category="fact",
        )
        await memory_index.verify(mid)
        mem = await storage.get_memory(mid)
        assert mem is not None
        assert mem["verified"] == 1
        assert mem["last_verified"] is not None


# ------------------------------------------------------------------
# REQ-07.6: Lightweight memory index
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.6")
class TestLightweightMemoryIndex:
    """Index holds summaries only; full content fetched on demand."""

    async def test_index_contains_summaries_not_content(
        self, memory_index: MemoryIndex
    ) -> None:
        """get_index returns summary strings without full content."""
        await memory_index.add(
            summary="Short summary here",
            content="This is a much longer detailed body of knowledge.",
            category="fact",
        )
        index = await memory_index.get_index()
        assert "Short summary here" in index[0]
        assert "much longer detailed body" not in index[0]

    async def test_fetch_detail_returns_full_content(
        self, memory_index: MemoryIndex
    ) -> None:
        """fetch_detail returns the complete MemoryEntry."""
        mid = await memory_index.add(
            summary="Summary",
            content="Full detailed content here.",
            category="decision",
        )
        entry = await memory_index.fetch_detail(mid)
        assert entry is not None
        assert entry.content == "Full detailed content here."
        assert entry.category == "decision"

    async def test_index_capped_at_200(self, memory_index: MemoryIndex) -> None:
        """Index never returns more than 200 entries."""
        for i in range(210):
            await memory_index.add(
                summary=f"Entry {i}",
                content=f"Content {i}",
                category="fact",
            )
        index = await memory_index.get_index()
        assert len(index) <= 200

    async def test_format_index_for_prompt(self, memory_index: MemoryIndex) -> None:
        """format_index_for_prompt produces injectable markdown."""
        await memory_index.add(
            summary="Uses async IO",
            content="All IO is async",
            category="codebase",
        )
        index = await memory_index.get_index()
        formatted = memory_index.format_index_for_prompt(index)
        assert "## Agent Memory Index" in formatted
        assert "Uses async IO" in formatted


# ------------------------------------------------------------------
# REQ-07.7: Memory consolidation
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.7")
class TestMemoryConsolidation:
    """Stale unverified memories are cleaned; duplicates are merged."""

    async def test_consolidate_removes_stale_unverified(
        self, memory_index: MemoryIndex, storage: Storage
    ) -> None:
        """Entries older than 30 days and never verified are deleted."""
        old_date = (datetime.now(UTC) - timedelta(days=35)).isoformat()
        assert storage._db is not None
        await storage._db.execute(
            "INSERT INTO memories"
            " (id, summary, content, category, verified, last_verified, created_at)"
            " VALUES (?, ?, ?, ?, 0, NULL, ?)",
            ("stale-id", "Stale fact", "Old info", "fact", old_date),
        )
        await storage._db.commit()

        fresh_id = await memory_index.add(
            summary="Fresh fact",
            content="New info",
            category="fact",
        )

        changes = await memory_index.consolidate()
        assert changes >= 1

        assert await memory_index.fetch_detail("stale-id") is None
        assert await memory_index.fetch_detail(fresh_id) is not None

    async def test_consolidate_deduplicates(self, memory_index: MemoryIndex) -> None:
        """Duplicate summaries are merged: only one copy remains."""
        await memory_index.add("Same summary", "Content v1", "fact")
        await memory_index.add("Same summary", "Content v2", "fact")

        index_before = await memory_index.get_index()
        dup_count = sum(1 for e in index_before if "Same summary" in e)
        assert dup_count == 2

        await memory_index.consolidate()

        index_after = await memory_index.get_index()
        dup_count_after = sum(1 for e in index_after if "Same summary" in e)
        assert dup_count_after == 1


# ------------------------------------------------------------------
# REQ-07.8: Context resets with handoff
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.8")
class TestContextResetHandoff:
    """When context is reset, a structured handoff preserves essential info."""

    def test_handoff_captures_task_and_decisions(self, ctx: ContextManager) -> None:
        """Handoff artifact contains task, decisions, and completed actions."""
        messages = [
            Message(role="system", content="sys"),
            Message(role="assistant", content="Decision: use SQLite over Postgres"),
            Message(role="tool", content="Created schema.sql successfully"),
            Message(role="assistant", content="Done writing schema."),
        ]
        artifact = ctx.create_handoff_artifact(messages, "Implement persistence layer")

        assert "## Context Handoff" in artifact
        assert "Implement persistence layer" in artifact
        assert "Decision: use SQLite over Postgres" in artifact
        assert "Created schema.sql successfully" in artifact
        assert "### Remaining Work" in artifact

    def test_handoff_with_no_decisions_or_actions(self, ctx: ContextManager) -> None:
        """Handoff still produces valid structure with empty conversation."""
        artifact = ctx.create_handoff_artifact([], "Empty task")
        assert "## Context Handoff" in artifact
        assert "Empty task" in artifact
        assert "(none recorded)" in artifact


# ------------------------------------------------------------------
# REQ-07.10: Static/dynamic prompt separation
# ------------------------------------------------------------------


@pytest.mark.req("REQ-07.10")
class TestStaticDynamicSeparation:
    """System prompt is static (cacheable); learnings + task are dynamic."""

    def test_static_part_equals_system_prompt(self) -> None:
        """Static partition contains only the system prompt."""
        static, dynamic = ContextManager.separate_static_dynamic(
            system_prompt="You are an autonomous agent.",
            learnings="Use guard clauses.",
            task="Fix bug #123",
        )
        assert static == "You are an autonomous agent."
        assert "guard clauses" in dynamic
        assert "Fix bug #123" in dynamic

    def test_static_part_stable_across_different_tasks(self) -> None:
        """Static part does not change when learnings or task change."""
        system = "You are a coder."
        s1, _ = ContextManager.separate_static_dynamic(system, "L1", "T1")
        s2, _ = ContextManager.separate_static_dynamic(system, "L2", "T2")
        assert s1 == s2 == system

    def test_dynamic_empty_when_no_learnings_or_task(self) -> None:
        """Dynamic part is empty string when both inputs are empty."""
        _, dynamic = ContextManager.separate_static_dynamic("sys", "", "")
        assert dynamic == ""


# ------------------------------------------------------------------
# REQ-09.2: Knowledge categories
# ------------------------------------------------------------------


@pytest.mark.req("REQ-09.2")
class TestKnowledgeCategories:
    """Learnings are stored with valid categories and filterable by category."""

    async def test_store_all_valid_categories(self, storage: Storage) -> None:
        """All four valid categories can be stored and retrieved."""
        categories = ["pattern", "anti_pattern", "tool_tip", "domain_knowledge"]
        ids = []
        for cat in categories:
            lid = await storage.add_learning(
                category=cat,
                content=f"Content for {cat}",
                confidence=0.5,
            )
            ids.append(lid)

        all_learnings = await storage.list_learnings()
        stored_cats = {l["category"] for l in all_learnings}
        assert stored_cats == set(categories)

    async def test_filter_by_category(self, storage: Storage) -> None:
        """list_learnings(category=...) returns only matching entries."""
        await storage.add_learning(category="pattern", content="Use early returns", confidence=0.6)
        await storage.add_learning(category="tool_tip", content="Use --verbose", confidence=0.6)
        await storage.add_learning(
            category="anti_pattern", content="Avoid busy waits", confidence=0.6
        )

        patterns = await storage.list_learnings(category="pattern")
        assert len(patterns) == 1
        assert patterns[0]["content"] == "Use early returns"

        tips = await storage.list_learnings(category="tool_tip")
        assert len(tips) == 1
        assert tips[0]["content"] == "Use --verbose"

    async def test_extract_learnings_respects_categories(self, storage: Storage) -> None:
        """extract_learnings via LLM stores only valid categories."""
        await storage.create_task("task-cat", "Test categories")
        await storage.update_task("task-cat", assigned_agent="agent-cat")
        await storage.register_agent("agent-cat", "coder")
        await storage.append_message("agent-cat", "user", "Do something")
        await storage.append_message("agent-cat", "assistant", "Done")

        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content=(
                    '{"category": "pattern", "content": "Validate inputs"}\n'
                    '{"category": "invalid_category", "content": "Should be skipped"}\n'
                    '{"category": "domain_knowledge", "content": "API uses REST"}\n'
                ),
                model="mock",
            )
        )

        result = await extract_learnings("task-cat", storage, provider)

        assert len(result) == 2
        cats = {r["category"] for r in result}
        assert cats == {"pattern", "domain_knowledge"}


# ------------------------------------------------------------------
# REQ-09.3: Confidence scoring
# ------------------------------------------------------------------


@pytest.mark.req("REQ-09.3")
class TestConfidenceScoring:
    """Confidence increases on validation, decreases on invalidation, decays over time."""

    async def test_initial_confidence(self, storage: Storage) -> None:
        """New learning starts at default confidence of 0.3."""
        lid = await storage.add_learning(
            category="pattern", content="Test", confidence=0.3
        )
        learning = await storage.get_learning(lid)
        assert learning is not None
        assert learning["confidence"] == pytest.approx(0.3)

    async def test_validate_increases_confidence(self, storage: Storage) -> None:
        """Each validation call increases confidence by the increment constant."""
        lid = await storage.add_learning(category="pattern", content="A", confidence=0.3)

        await storage.validate_learning(lid)
        after = await storage.get_learning(lid)
        assert after is not None
        expected = 0.3 + CONFIDENCE_VALIDATE_INCREMENT
        assert after["confidence"] == pytest.approx(expected)

    async def test_invalidate_decreases_confidence(self, storage: Storage) -> None:
        """Invalidation decreases confidence by the decrement constant."""
        lid = await storage.add_learning(category="pattern", content="B", confidence=0.6)

        await storage.invalidate_learning(lid)
        after = await storage.get_learning(lid)
        assert after is not None
        expected = 0.6 - CONFIDENCE_INVALIDATE_DECREMENT
        assert after["confidence"] == pytest.approx(expected)

    async def test_confidence_capped_at_one(self, storage: Storage) -> None:
        """Confidence cannot exceed 1.0 no matter how many validations."""
        lid = await storage.add_learning(category="pattern", content="C", confidence=0.95)

        await storage.validate_learning(lid)
        await storage.validate_learning(lid)
        await storage.validate_learning(lid)

        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] <= 1.0

    async def test_confidence_floored_at_zero(self, storage: Storage) -> None:
        """Confidence cannot go below 0.0 on repeated invalidation."""
        lid = await storage.add_learning(category="pattern", content="D", confidence=0.1)

        await storage.invalidate_learning(lid)
        await storage.invalidate_learning(lid)
        await storage.invalidate_learning(lid)

        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] >= 0.0

    async def test_decay_reduces_stale_confidence(self, storage: Storage) -> None:
        """decay_learnings reduces confidence of entries not validated recently."""
        lid = await storage.add_learning(category="pattern", content="E", confidence=0.8)

        # Backdate the created_at to simulate age
        old_date = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        assert storage._db is not None
        await storage._db.execute(
            "UPDATE learnings SET created_at = ?, last_validated = NULL WHERE id = ?",
            (old_date, lid),
        )
        await storage._db.commit()

        affected = await storage.decay_learnings(days_since_validation=30)
        assert affected >= 1

        after = await storage.get_learning(lid)
        assert after is not None
        expected = 0.8 - CONFIDENCE_DECAY_DECREMENT
        assert after["confidence"] == pytest.approx(expected)

    async def test_injection_filters_low_confidence(self, storage: Storage) -> None:
        """format_learnings_for_injection excludes items below MIN_INJECTION_CONFIDENCE."""
        low = {"category": "pattern", "content": "Low conf", "confidence": 0.2}
        high = {"category": "pattern", "content": "High conf", "confidence": 0.8}

        result = format_learnings_for_injection([low, high])
        assert "High conf" in result
        assert "Low conf" not in result

    async def test_confidence_lifecycle(self, storage: Storage) -> None:
        """Full lifecycle: add -> validate x2 -> invalidate -> verify final score."""
        lid = await storage.add_learning(category="tool_tip", content="Lifecycle", confidence=0.3)

        await storage.validate_learning(lid)   # 0.3 + 0.1 = 0.4
        await storage.validate_learning(lid)   # 0.4 + 0.1 = 0.5

        mid = await storage.get_learning(lid)
        assert mid is not None
        assert mid["confidence"] == pytest.approx(0.5)

        await storage.invalidate_learning(lid)  # 0.5 - 0.15 = 0.35

        final = await storage.get_learning(lid)
        assert final is not None
        assert final["confidence"] == pytest.approx(0.35)

        # At 0.35, this learning should NOT appear in injection
        injection = format_learnings_for_injection([final])
        assert injection == ""
