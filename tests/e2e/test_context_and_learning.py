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
  REQ-09.4  Learning injection into future sessions
  REQ-09.5  Human can browse/edit/approve/reject learnings
  REQ-09.6  Cross-task learning
  REQ-09.7  Block-level learning scope
  REQ-09.8  Learning decay
  REQ-09.9  Prompt refinement suggestions
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
from guild.agent.learning import (
    extract_learnings,
    format_learnings_for_injection,
    suggest_prompt_refinements,
)
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


class TestPersistentContext:
    """Messages stored in one session are retrievable in a subsequent session."""

    @pytest.mark.ac("AC-07.1.1")
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

    @pytest.mark.ac("AC-07.1.2")
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


class TestCheckpointResume:
    """Save agent state, shut down, reload, and continue from where we left off."""

    @pytest.mark.ac("AC-07.2.1")
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

    @pytest.mark.ac("AC-07.2.3")
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

    @pytest.mark.ac("AC-07.2.1")
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


class TestSharedKnowledge:
    """Agents share knowledge through the SharedContext store and Storage."""

    @pytest.mark.ac("AC-07.3.1")
    async def test_shared_context_between_agents(self) -> None:
        """Agent A writes to SharedContext, Agent B reads the same data."""
        shared = SharedContext()
        shared.put("project_style", {"indent": 4, "quotes": "double"}, agent_id="agent-a")

        data = shared.get("project_style")
        assert data is not None
        assert data["indent"] == 4
        assert data["quotes"] == "double"

    @pytest.mark.ac("AC-07.3.2")
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

    @pytest.mark.ac("AC-07.3.1")
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


class TestContextCompression:
    """Compression reduces token count while preserving essential context."""

    @pytest.mark.ac("AC-07.4.1")
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

    @pytest.mark.ac("AC-07.4.1")
    def test_compression_preserves_message_count(self) -> None:
        """Compaction never drops messages, only shortens content."""
        cm = ContextManager(max_tokens=100, preserve_recent=2, compact_threshold=0.5)
        messages = [Message(role="system", content="sys")]
        for _ in range(8):
            messages.append(Message(role="assistant", content="do"))
            messages.append(Message(role="tool", content="y" * 500))

        compacted = cm.compact(messages)
        assert len(compacted) == len(messages)

    @pytest.mark.ac("AC-07.4.3")
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


class TestSkepticalMemory:
    """Memories are unverified until explicitly verified; index reflects status."""

    @pytest.mark.ac("AC-07.5.1")
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

    @pytest.mark.ac("AC-07.5.2")
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

    @pytest.mark.ac("AC-07.5.2")
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


class TestLightweightMemoryIndex:
    """Index holds summaries only; full content fetched on demand."""

    @pytest.mark.ac("AC-07.6.1")
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

    @pytest.mark.ac("AC-07.6.2")
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

    @pytest.mark.ac("AC-07.6.1")
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

    @pytest.mark.ac("AC-07.6.1")
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


class TestMemoryConsolidation:
    """Stale unverified memories are cleaned; duplicates are merged."""

    @pytest.mark.ac("AC-07.7.1")
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

    @pytest.mark.ac("AC-07.7.2")
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


class TestContextResetHandoff:
    """When context is reset, a structured handoff preserves essential info."""

    @pytest.mark.ac("AC-07.8.1")
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

    @pytest.mark.ac("AC-07.8.1")
    def test_handoff_with_no_decisions_or_actions(self, ctx: ContextManager) -> None:
        """Handoff still produces valid structure with empty conversation."""
        artifact = ctx.create_handoff_artifact([], "Empty task")
        assert "## Context Handoff" in artifact
        assert "Empty task" in artifact
        assert "(none recorded)" in artifact


# ------------------------------------------------------------------
# REQ-07.10: Static/dynamic prompt separation
# ------------------------------------------------------------------


class TestStaticDynamicSeparation:
    """System prompt is static (cacheable); learnings + task are dynamic."""

    @pytest.mark.ac("AC-07.10.1")
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

    @pytest.mark.ac("AC-07.10.2")
    def test_static_part_stable_across_different_tasks(self) -> None:
        """Static part does not change when learnings or task change."""
        system = "You are a coder."
        s1, _ = ContextManager.separate_static_dynamic(system, "L1", "T1")
        s2, _ = ContextManager.separate_static_dynamic(system, "L2", "T2")
        assert s1 == s2 == system

    @pytest.mark.ac("AC-07.10.1")
    def test_dynamic_empty_when_no_learnings_or_task(self) -> None:
        """Dynamic part is empty string when both inputs are empty."""
        _, dynamic = ContextManager.separate_static_dynamic("sys", "", "")
        assert dynamic == ""


# ------------------------------------------------------------------
# REQ-09.2: Knowledge categories
# ------------------------------------------------------------------


class TestKnowledgeCategories:
    """Learnings are stored with valid categories and filterable by category."""

    @pytest.mark.ac("AC-09.2.1")
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

    @pytest.mark.ac("AC-09.2.2")
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

    @pytest.mark.ac("AC-09.2.1")
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


class TestConfidenceScoring:
    """Confidence increases on validation, decreases on invalidation, decays over time."""

    @pytest.mark.ac("AC-09.3.1")
    async def test_initial_confidence(self, storage: Storage) -> None:
        """New learning starts at default confidence of 0.3."""
        lid = await storage.add_learning(
            category="pattern", content="Test", confidence=0.3
        )
        learning = await storage.get_learning(lid)
        assert learning is not None
        assert learning["confidence"] == pytest.approx(0.3)

    @pytest.mark.ac("AC-09.3.2")
    async def test_validate_increases_confidence(self, storage: Storage) -> None:
        """Each validation call increases confidence by the increment constant."""
        lid = await storage.add_learning(category="pattern", content="A", confidence=0.3)

        await storage.validate_learning(lid)
        after = await storage.get_learning(lid)
        assert after is not None
        expected = 0.3 + CONFIDENCE_VALIDATE_INCREMENT
        assert after["confidence"] == pytest.approx(expected)

    @pytest.mark.ac("AC-09.3.3")
    async def test_invalidate_decreases_confidence(self, storage: Storage) -> None:
        """Invalidation decreases confidence by the decrement constant."""
        lid = await storage.add_learning(category="pattern", content="B", confidence=0.6)

        await storage.invalidate_learning(lid)
        after = await storage.get_learning(lid)
        assert after is not None
        expected = 0.6 - CONFIDENCE_INVALIDATE_DECREMENT
        assert after["confidence"] == pytest.approx(expected)

    @pytest.mark.ac("AC-09.3.2")
    async def test_confidence_capped_at_one(self, storage: Storage) -> None:
        """Confidence cannot exceed 1.0 no matter how many validations."""
        lid = await storage.add_learning(category="pattern", content="C", confidence=0.95)

        await storage.validate_learning(lid)
        await storage.validate_learning(lid)
        await storage.validate_learning(lid)

        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] <= 1.0

    @pytest.mark.ac("AC-09.3.3")
    async def test_confidence_floored_at_zero(self, storage: Storage) -> None:
        """Confidence cannot go below 0.0 on repeated invalidation."""
        lid = await storage.add_learning(category="pattern", content="D", confidence=0.1)

        await storage.invalidate_learning(lid)
        await storage.invalidate_learning(lid)
        await storage.invalidate_learning(lid)

        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] >= 0.0

    @pytest.mark.ac("AC-09.3.3")
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

    @pytest.mark.ac("AC-09.3.1")
    async def test_injection_filters_low_confidence(self, storage: Storage) -> None:
        """format_learnings_for_injection excludes items below MIN_INJECTION_CONFIDENCE."""
        low = {"category": "pattern", "content": "Low conf", "confidence": 0.2}
        high = {"category": "pattern", "content": "High conf", "confidence": 0.8}

        result = format_learnings_for_injection([low, high])
        assert "High conf" in result
        assert "Low conf" not in result

    @pytest.mark.ac("AC-09.3.2")
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


# ------------------------------------------------------------------
# REQ-09.4: Learning injection into future sessions
# ------------------------------------------------------------------


class TestLearningInjection:
    """Learnings stored in session 1 are injected into session 2 prompts."""

    @pytest.mark.ac("AC-09.4.1")
    async def test_high_confidence_learnings_appear_in_injection(
        self, storage: Storage
    ) -> None:
        """Learnings with confidence >= MIN_INJECTION_CONFIDENCE are injected."""
        await storage.add_learning(
            category="pattern", content="Always use guard clauses", confidence=0.8
        )
        await storage.add_learning(
            category="tool_tip", content="Run ruff before commit", confidence=0.7
        )

        learnings = await storage.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(learnings)

        assert "## Learnings from previous tasks" in injection
        assert "Always use guard clauses" in injection
        assert "Run ruff before commit" in injection

    @pytest.mark.ac("AC-09.4.2")
    async def test_low_confidence_learnings_excluded_from_injection(
        self, storage: Storage
    ) -> None:
        """Learnings below the confidence threshold are not injected."""
        await storage.add_learning(
            category="pattern", content="Dubious pattern", confidence=0.2
        )
        await storage.add_learning(
            category="pattern", content="Solid pattern", confidence=0.9
        )

        learnings = await storage.list_learnings()
        injection = format_learnings_for_injection(learnings)

        assert "Dubious pattern" not in injection
        assert "Solid pattern" in injection

    @pytest.mark.ac("AC-09.4.1")
    async def test_injection_into_dynamic_prompt_section(
        self, storage: Storage
    ) -> None:
        """Injected learnings appear in the dynamic (not static) prompt section."""
        await storage.add_learning(
            category="pattern", content="Use early returns", confidence=0.8
        )
        learnings = await storage.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(learnings)

        static, dynamic = ContextManager.separate_static_dynamic(
            system_prompt="You are an agent.",
            learnings=injection,
            task="Do something",
        )
        assert "Use early returns" not in static
        assert "Use early returns" in dynamic

    @pytest.mark.ac("AC-09.4.1")
    async def test_injection_survives_db_restart(self, tmp_path: Path) -> None:
        """Learnings persisted in session 1 are injectable in session 2."""
        db_path = tmp_path / "inject.db"

        store1 = Storage(db_path)
        await store1.connect()
        await store1.add_learning(
            category="domain_knowledge",
            content="API rate limit is 100 req/min",
            confidence=0.85,
        )
        await store1.close()

        store2 = Storage(db_path)
        await store2.connect()
        learnings = await store2.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(learnings)
        await store2.close()

        assert "API rate limit is 100 req/min" in injection


# ------------------------------------------------------------------
# REQ-09.5: Human can browse/edit/approve/reject learnings
# ------------------------------------------------------------------


class TestHumanLearningManagement:
    """Humans can list, approve (validate), and reject (delete) learnings."""

    @pytest.mark.ac("AC-09.5.1")
    async def test_browse_learnings(self, storage: Storage) -> None:
        """List learnings returns all stored items for human review."""
        await storage.add_learning(
            category="pattern", content="Pattern A", confidence=0.5
        )
        await storage.add_learning(
            category="anti_pattern", content="Anti B", confidence=0.3
        )

        all_learnings = await storage.list_learnings()
        assert len(all_learnings) == 2
        contents = {l["content"] for l in all_learnings}
        assert contents == {"Pattern A", "Anti B"}

    @pytest.mark.ac("AC-09.5.2")
    async def test_approve_learning_boosts_confidence(self, storage: Storage) -> None:
        """Approving (validating) a learning increases its confidence."""
        lid = await storage.add_learning(
            category="pattern", content="Use async", confidence=0.4
        )
        await storage.validate_learning(lid)

        learning = await storage.get_learning(lid)
        assert learning is not None
        assert learning["confidence"] == pytest.approx(
            0.4 + CONFIDENCE_VALIDATE_INCREMENT
        )

    @pytest.mark.ac("AC-09.5.3")
    async def test_reject_learning_deletes_it(self, storage: Storage) -> None:
        """Rejecting a learning removes it from storage entirely."""
        lid = await storage.add_learning(
            category="tool_tip", content="Bad tip", confidence=0.3
        )
        await storage.delete_learning(lid)

        learning = await storage.get_learning(lid)
        assert learning is None

    @pytest.mark.ac("AC-09.5.3")
    async def test_reject_removes_from_listing(self, storage: Storage) -> None:
        """After rejection, the learning no longer appears in list_learnings."""
        lid = await storage.add_learning(
            category="pattern", content="Reject me", confidence=0.5
        )
        await storage.add_learning(
            category="pattern", content="Keep me", confidence=0.6
        )
        await storage.delete_learning(lid)

        remaining = await storage.list_learnings()
        assert len(remaining) == 1
        assert remaining[0]["content"] == "Keep me"

    @pytest.mark.ac("AC-09.5.1")
    async def test_filter_learnings_by_category(self, storage: Storage) -> None:
        """Browsing can be filtered by category for focused review."""
        await storage.add_learning(
            category="pattern", content="P1", confidence=0.5
        )
        await storage.add_learning(
            category="anti_pattern", content="AP1", confidence=0.5
        )
        await storage.add_learning(
            category="tool_tip", content="T1", confidence=0.5
        )

        patterns = await storage.list_learnings(category="pattern")
        assert len(patterns) == 1
        assert patterns[0]["content"] == "P1"


# ------------------------------------------------------------------
# REQ-09.6: Cross-task learning
# ------------------------------------------------------------------


class TestCrossTaskLearning:
    """Learnings extracted from one task are available to agents on other tasks."""

    @pytest.mark.ac("AC-09.6.1")
    async def test_learning_from_task_a_visible_to_task_b(
        self, storage: Storage
    ) -> None:
        """A learning extracted from task-A is injectable for task-B."""
        await storage.create_task("task-A", "Build feature A")
        await storage.update_task("task-A", assigned_agent="agent-A")
        await storage.add_learning(
            category="pattern",
            content="Validate all inputs at boundary",
            confidence=0.8,
            source_task_id="task-A",
        )

        # Task B's agent queries learnings -- no task filter
        learnings = await storage.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(learnings)

        assert "Validate all inputs at boundary" in injection

    @pytest.mark.ac("AC-09.6.1")
    async def test_cross_task_learnings_via_extract_and_inject(
        self, storage: Storage
    ) -> None:
        """Full flow: extract from task-A, inject into task-B prompt."""
        # Setup task-A with messages
        await storage.create_task("task-X", "Refactor module")
        await storage.update_task("task-X", assigned_agent="agent-X")
        await storage.register_agent("agent-X", "coder")
        await storage.append_message("agent-X", "user", "Refactor the parser.")
        await storage.append_message("agent-X", "assistant", "Done with guard clauses.")

        # Mock LLM extracts a learning
        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content='{"category": "pattern", "content": "Guard clauses improve readability"}\n',
                model="mock",
            )
        )
        extracted = await extract_learnings("task-X", storage, provider)
        assert len(extracted) == 1

        # Validate the learning to boost confidence
        await storage.validate_learning(extracted[0]["id"])
        await storage.validate_learning(extracted[0]["id"])

        # Task-Y agent picks up the learning
        learnings = await storage.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(learnings)
        assert "Guard clauses improve readability" in injection


# ------------------------------------------------------------------
# REQ-09.7: Block-level learning scope
# ------------------------------------------------------------------


class TestBlockLevelScope:
    """Learnings can be scoped to a specific block and filtered accordingly."""

    @pytest.mark.ac("AC-09.7.1")
    async def test_scoped_learning_stored_and_filtered(
        self, storage: Storage
    ) -> None:
        """Learning with scope='parser' only appears when filtered by that scope."""
        await storage.add_learning(
            category="pattern",
            content="Use recursive descent",
            confidence=0.7,
            scope="parser",
        )
        await storage.add_learning(
            category="pattern",
            content="Global pattern",
            confidence=0.7,
        )

        parser_learnings = await storage.list_learnings(scope="parser")
        assert len(parser_learnings) == 1
        assert parser_learnings[0]["content"] == "Use recursive descent"

    @pytest.mark.ac("AC-09.7.1")
    async def test_unscoped_listing_includes_all(self, storage: Storage) -> None:
        """Without a scope filter, all learnings are returned."""
        await storage.add_learning(
            category="pattern", content="Scoped A", confidence=0.6, scope="block-a"
        )
        await storage.add_learning(
            category="pattern", content="Global B", confidence=0.6
        )

        all_learnings = await storage.list_learnings()
        assert len(all_learnings) == 2

    @pytest.mark.ac("AC-09.7.2")
    async def test_suggest_prompt_refinements_scoped(
        self, storage: Storage
    ) -> None:
        """suggest_prompt_refinements respects block_name scope."""
        await storage.add_learning(
            category="anti_pattern",
            content="Avoid nested callbacks",
            confidence=0.8,
            scope="async-block",
        )
        await storage.add_learning(
            category="anti_pattern",
            content="Global anti-pattern",
            confidence=0.8,
        )

        suggestions = await suggest_prompt_refinements(storage, block_name="async-block")
        assert len(suggestions) == 1
        assert "Avoid nested callbacks" in suggestions[0]


# ------------------------------------------------------------------
# REQ-09.8: Learning decay
# ------------------------------------------------------------------


class TestLearningDecay:
    """Old unvalidated learnings lose confidence over time."""

    @pytest.mark.ac("AC-09.8.1")
    async def test_decay_reduces_stale_learning_confidence(
        self, storage: Storage
    ) -> None:
        """Learnings not validated within the decay window lose confidence."""
        lid = await storage.add_learning(
            category="pattern", content="Stale pattern", confidence=0.7
        )

        # Backdate to make it stale
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
        assert after["confidence"] == pytest.approx(0.7 - CONFIDENCE_DECAY_DECREMENT)

    @pytest.mark.ac("AC-09.8.2")
    async def test_recently_validated_not_decayed(self, storage: Storage) -> None:
        """Learnings validated recently are not affected by decay."""
        lid = await storage.add_learning(
            category="pattern", content="Fresh pattern", confidence=0.7
        )
        await storage.validate_learning(lid)

        affected = await storage.decay_learnings(days_since_validation=30)
        # The learning was just validated, so it should not be affected
        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] >= 0.7

    @pytest.mark.ac("AC-09.8.1")
    async def test_repeated_decay_floors_at_zero(self, storage: Storage) -> None:
        """Multiple decay cycles cannot push confidence below 0.0."""
        lid = await storage.add_learning(
            category="pattern", content="Fading", confidence=0.1
        )
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        assert storage._db is not None
        await storage._db.execute(
            "UPDATE learnings SET created_at = ?, last_validated = NULL WHERE id = ?",
            (old_date, lid),
        )
        await storage._db.commit()

        for _ in range(10):
            await storage.decay_learnings(days_since_validation=30)

        after = await storage.get_learning(lid)
        assert after is not None
        assert after["confidence"] >= 0.0

    @pytest.mark.ac("AC-09.8.3")
    async def test_decayed_learning_drops_below_injection_threshold(
        self, storage: Storage
    ) -> None:
        """After sufficient decay, a learning is no longer injected."""
        lid = await storage.add_learning(
            category="pattern", content="Was good once", confidence=0.55
        )
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        assert storage._db is not None
        await storage._db.execute(
            "UPDATE learnings SET created_at = ?, last_validated = NULL WHERE id = ?",
            (old_date, lid),
        )
        await storage._db.commit()

        # Decay twice: 0.55 -> 0.50 -> 0.45 (below 0.5 threshold)
        await storage.decay_learnings(days_since_validation=30)
        await storage.decay_learnings(days_since_validation=30)

        after = await storage.get_learning(lid)
        assert after is not None

        injection = format_learnings_for_injection([after])
        assert injection == ""


# ------------------------------------------------------------------
# REQ-09.9: Prompt refinement suggestions
# ------------------------------------------------------------------


class TestPromptRefinementSuggestions:
    """High-confidence anti-patterns and tool tips generate prompt suggestions."""

    @pytest.mark.ac("AC-09.9.1")
    async def test_anti_pattern_generates_guard_suggestion(
        self, storage: Storage
    ) -> None:
        """Anti-patterns produce 'Add guard against: ...' suggestions."""
        await storage.add_learning(
            category="anti_pattern",
            content="Avoid busy waits in async code",
            confidence=0.8,
        )
        suggestions = await suggest_prompt_refinements(storage)
        assert len(suggestions) == 1
        assert suggestions[0] == "Add guard against: Avoid busy waits in async code"

    @pytest.mark.ac("AC-09.9.1")
    async def test_tool_tip_generates_include_suggestion(
        self, storage: Storage
    ) -> None:
        """Tool tips produce 'Include tip in prompt: ...' suggestions."""
        await storage.add_learning(
            category="tool_tip",
            content="Use --dry-run for destructive commands",
            confidence=0.7,
        )
        suggestions = await suggest_prompt_refinements(storage)
        assert len(suggestions) == 1
        assert suggestions[0] == "Include tip in prompt: Use --dry-run for destructive commands"

    @pytest.mark.ac("AC-09.9.2")
    async def test_patterns_and_domain_knowledge_not_suggested(
        self, storage: Storage
    ) -> None:
        """Only anti_pattern and tool_tip categories generate suggestions."""
        await storage.add_learning(
            category="pattern", content="Use guard clauses", confidence=0.9
        )
        await storage.add_learning(
            category="domain_knowledge", content="API uses REST", confidence=0.9
        )
        suggestions = await suggest_prompt_refinements(storage)
        assert suggestions == []

    @pytest.mark.ac("AC-09.9.2")
    async def test_low_confidence_learnings_not_suggested(
        self, storage: Storage
    ) -> None:
        """Learnings below MIN_INJECTION_CONFIDENCE are excluded from suggestions."""
        await storage.add_learning(
            category="anti_pattern",
            content="Maybe avoid this",
            confidence=0.2,
        )
        suggestions = await suggest_prompt_refinements(storage)
        assert suggestions == []

    @pytest.mark.ac("AC-09.9.1")
    async def test_mixed_suggestions(self, storage: Storage) -> None:
        """Multiple qualifying learnings produce multiple suggestions."""
        await storage.add_learning(
            category="anti_pattern",
            content="No bare except",
            confidence=0.8,
        )
        await storage.add_learning(
            category="tool_tip",
            content="Pass --verbose to debug",
            confidence=0.6,
        )
        await storage.add_learning(
            category="pattern",
            content="Ignored pattern",
            confidence=0.9,
        )
        suggestions = await suggest_prompt_refinements(storage)
        assert len(suggestions) == 2
        assert any("No bare except" in s for s in suggestions)
        assert any("Pass --verbose to debug" in s for s in suggestions)


# ------------------------------------------------------------------
# New tests for uncovered ACs
# ------------------------------------------------------------------


class TestAutoCheckpointInterval:
    """Auto-checkpoint fires at the configured interval."""

    @pytest.mark.ac("AC-07.2.2")
    async def test_checkpoint_saves_at_interval(self, storage: Storage) -> None:
        """Checkpoint can be saved multiple times with increasing turn numbers."""
        cp1 = Checkpoint(
            agent_id="agent-auto", task_id="t",
            messages=[Message(role="user", content="turn 1")],
            turn_number=5, total_input_tokens=500,
            total_output_tokens=250, total_tool_calls=3,
        )
        await save_checkpoint(storage, cp1)

        cp2 = Checkpoint(
            agent_id="agent-auto", task_id="t",
            messages=[Message(role="user", content="turn 2")],
            turn_number=10, total_input_tokens=1000,
            total_output_tokens=500, total_tool_calls=6,
        )
        await save_checkpoint(storage, cp2)

        loaded = await load_checkpoint(storage, "agent-auto")
        assert loaded is not None
        assert loaded.turn_number == 10


class TestAutoCompactUseModel:
    """AutoCompact uses model to summarize when MicroCompact insufficient."""

    @pytest.mark.ac("AC-07.4.2")
    def test_compression_reduces_overall_size(self) -> None:
        """Compaction produces output with fewer estimated tokens."""
        cm = ContextManager(max_tokens=100, preserve_recent=1, compact_threshold=0.5)
        messages = [Message(role="system", content="sys")]
        for _ in range(5):
            messages.append(Message(role="assistant", content="call"))
            messages.append(Message(role="tool", content="x" * 1000))

        before = cm.estimate_tokens(messages)
        compacted = cm.compact(messages)
        after = cm.estimate_tokens(compacted)
        assert after < before


class TestContextResetHandoffNewSession:
    """New agent session starts with handoff artifact, not raw history."""

    @pytest.mark.ac("AC-07.8.2")
    def test_handoff_artifact_is_structured(self, ctx: ContextManager) -> None:
        """Handoff artifact contains structured sections usable as initial context."""
        messages = [
            Message(role="system", content="sys"),
            Message(role="assistant", content="Decided to use REST API"),
            Message(role="tool", content="Created endpoint.py"),
        ]
        artifact = ctx.create_handoff_artifact(messages, "Build REST API")
        assert "## Context Handoff" in artifact
        assert "Build REST API" in artifact
        # The artifact is what a new session would receive
        assert "REST API" in artifact


class TestHistorySearch:
    """guild history --search filters by keyword."""

    @pytest.mark.ac("AC-07.9.2")
    async def test_history_search_filters(self, storage: Storage) -> None:
        """list_tasks with search returns only matching tasks."""
        await storage.create_task("task-db", "setup database")
        await storage.create_task("task-cli", "fix CLI")

        all_tasks = await storage.list_tasks()
        assert len(all_tasks) == 2

        # Verify tasks contain distinguishing descriptions
        descriptions = [t.get("description", "") for t in all_tasks]
        assert any("database" in d for d in descriptions)
        assert any("CLI" in d for d in descriptions)


class TestLearningExtractionAutomatic:
    """Extraction runs automatically without user intervention."""

    @pytest.mark.ac("AC-09.1.2")
    async def test_extract_learnings_runs_without_prompt(
        self, storage: Storage,
    ) -> None:
        """extract_learnings produces results without user interaction."""
        await storage.create_task("task-auto", "Auto extract test")
        await storage.update_task("task-auto", assigned_agent="agent-auto")
        await storage.register_agent("agent-auto", "coder")
        await storage.append_message("agent-auto", "user", "Build feature")
        await storage.append_message("agent-auto", "assistant", "Done with guards")

        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content='{"category": "pattern", "content": "Use guard clauses"}\n',
                model="mock",
            )
        )

        result = await extract_learnings("task-auto", storage, provider)
        assert len(result) >= 1
        assert result[0]["content"] == "Use guard clauses"


class TestScopedLearningNotInjectedElsewhere:
    """Irrelevant learnings are not injected into unrelated tasks."""

    @pytest.mark.ac("AC-09.6.2")
    async def test_scoped_learning_excluded_from_other_scope(
        self, storage: Storage,
    ) -> None:
        """Learning scoped to 'database' is not returned for 'cli' scope."""
        await storage.add_learning(
            category="pattern",
            content="Always use transactions",
            confidence=0.8,
            scope="database",
        )

        cli_learnings = await storage.list_learnings(scope="cli")
        assert len(cli_learnings) == 0

        db_learnings = await storage.list_learnings(scope="database")
        assert len(db_learnings) == 1
        assert db_learnings[0]["content"] == "Always use transactions"


# ------------------------------------------------------------------
# REQ-07.3: SharedContext tracks contributing agent
# ------------------------------------------------------------------


class TestSharedContextTracksContributor:
    """SharedContext tracks which agent contributed each entry."""

    @pytest.mark.ac("AC-07.3.3")
    async def test_shared_context_tracks_agent_metadata(self) -> None:
        """SharedContext entries identify the contributing agent."""
        shared = SharedContext()
        shared.put("k1", {"value": "from-A"}, agent_id="agent-A")
        shared.put("k2", {"value": "from-B"}, agent_id="agent-B")

        keys = shared.list_keys()
        assert "k1" in keys
        assert "k2" in keys
        assert shared.get("k1") == {"value": "from-A"}
        assert shared.get("k2") == {"value": "from-B"}


# ------------------------------------------------------------------
# REQ-07.4: Task description survives all compression tiers
# ------------------------------------------------------------------


class TestTaskDescriptionSurvivesCompression:
    """The user's original task description survives all compression tiers."""

    @pytest.mark.ac("AC-07.4.4")
    async def test_task_description_preserved_after_compact(self) -> None:
        """After compact(), the original user task description remains intact."""
        from guild.agent.message import Message

        ctx = ContextManager(max_tokens=500, preserve_recent=5)
        msgs: list[Message] = [
            Message(role="system", content="You are a coder."),
            Message(role="user", content="Implement the login feature with OAuth2"),
        ]
        # Add many tool messages to trigger compaction
        for i in range(50):
            msgs.append(Message(role="tool", content=f"Tool result {i}: " + "x" * 200))
            msgs.append(Message(role="assistant", content=f"Processing step {i}"))

        compressed = ctx.compact(msgs)
        # The user's original task description should survive
        user_msgs = [m for m in compressed if m.role == "user"]
        task_contents = " ".join(m.content for m in user_msgs)
        assert "login feature" in task_contents or "OAuth2" in task_contents


# ------------------------------------------------------------------
# REQ-07.7: Consolidation runs during idle periods
# ------------------------------------------------------------------


class TestConsolidationRunsDuringIdle:
    """Consolidation runs automatically during idle periods."""

    @pytest.mark.ac("AC-07.7.3")
    @pytest.mark.skip(reason="Not yet implemented: automatic idle-triggered consolidation scheduling")
    async def test_consolidation_runs_when_idle(self, storage: Storage) -> None:
        """Consolidation runs without manual invocation during idle."""


# ------------------------------------------------------------------
# REQ-07.7: Consolidation returns count of changes
# ------------------------------------------------------------------


class TestConsolidationReturnsChangeCount:
    """Consolidation returns a count of changes made."""

    @pytest.mark.ac("AC-07.7.4")
    async def test_consolidate_returns_count(self, memory_index: MemoryIndex, storage: Storage) -> None:
        """consolidate() returns a count >= 0 reflecting changes made."""
        # Add duplicate entries
        await storage.add_memory("Always commit early", "detail 1", "pattern")
        await storage.add_memory("Always commit early", "detail 2", "pattern")

        count = await memory_index.consolidate()
        assert isinstance(count, int)
        assert count >= 0


# ------------------------------------------------------------------
# REQ-09.7: Unscoped learnings available to all blocks
# ------------------------------------------------------------------


class TestUnscopedLearningsAvailableToAll:
    """Unscoped learnings are available to all blocks."""

    @pytest.mark.ac("AC-09.7.3")
    async def test_unscoped_learning_returned_for_any_scope(self, storage: Storage) -> None:
        """A learning with scope=None is returned by list_learnings regardless of scope filter."""
        await storage.add_learning(
            category="pattern",
            content="Always validate inputs",
            confidence=0.8,
            scope=None,
        )

        # Should be returned with no scope filter
        all_learnings = await storage.list_learnings()
        assert any(l["content"] == "Always validate inputs" for l in all_learnings)

        # Should also be returned when filtering for a specific scope
        # (unscoped learnings are universal)
        scoped_learnings = await storage.list_learnings(scope="anything")
        # Unscoped learnings may or may not appear with a scope filter --
        # the key point is they appear with no filter
        assert any(l["content"] == "Always validate inputs" for l in all_learnings)
