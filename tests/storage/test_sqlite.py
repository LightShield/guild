"""Tests for storage/sqlite.py — SQLite persistence layer (REQ-06.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.storage.sqlite import Storage
from guild.storage.audit import DecisionRecord
from guild.storage.learnings import LearningRecord
from guild.storage.questions import QuestionRecord


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


@pytest.mark.unit
class TestConnection:
    """Database creation and schema initialization."""

    async def test_connect_creates_database_file(self, tmp_path: Path) -> None:
        """Calling connect() creates the SQLite file on disk."""
        db_path = tmp_path / "guild.db"
        store = Storage(db_path)
        await store.connect()
        try:
            assert db_path.exists()
        finally:
            await store.close()

    async def test_connect_creates_schema_tables(self, storage: Storage) -> None:
        """After connect(), all expected tables exist in the database."""
        tables = await storage._get_tables()
        assert "tasks" in tables
        assert "agents" in tables
        assert "messages" in tables
        assert "audit_log" in tables


@pytest.mark.unit
class TestTasks:
    """Task CRUD operations."""

    async def test_create_task_persists_to_db(self, storage: Storage) -> None:
        """Creating a task stores it in the database."""
        await storage.create_task("task-1", "Build the feature")
        task = await storage.get_task("task-1")
        assert task is not None
        assert task["task_id"] == "task-1"
        assert task["description"] == "Build the feature"
        assert task["status"] == "pending"

    async def test_get_task_returns_stored_task(self, storage: Storage) -> None:
        """get_task retrieves a previously stored task with all fields."""
        await storage.create_task("task-2", "Fix the bug")
        task = await storage.get_task("task-2")
        assert task is not None
        assert task["task_id"] == "task-2"
        assert task["description"] == "Fix the bug"
        assert "created_at" in task

    async def test_get_task_returns_none_for_missing_id(self, storage: Storage) -> None:
        """get_task returns None for a task_id that doesn't exist."""
        result = await storage.get_task("nonexistent")
        assert result is None

    async def test_list_tasks_returns_all_tasks(self, storage: Storage) -> None:
        """list_tasks with no filter returns all stored tasks."""
        await storage.create_task("t1", "Task one")
        await storage.create_task("t2", "Task two")
        await storage.create_task("t3", "Task three")
        tasks = await storage.list_tasks()
        assert len(tasks) == 3

    async def test_list_tasks_filters_by_status(self, storage: Storage) -> None:
        """list_tasks with status filter returns only matching tasks."""
        await storage.create_task("t1", "Task one")
        await storage.create_task("t2", "Task two")
        await storage.update_task("t2", status="running")
        pending = await storage.list_tasks(status="pending")
        running = await storage.list_tasks(status="running")
        assert len(pending) == 1
        assert pending[0]["task_id"] == "t1"
        assert len(running) == 1
        assert running[0]["task_id"] == "t2"

    async def test_update_task_modifies_fields(self, storage: Storage) -> None:
        """update_task changes the specified fields."""
        await storage.create_task("t1", "Original")
        await storage.update_task("t1", status="completed", result="success")
        task = await storage.get_task("t1")
        assert task["status"] == "completed"
        assert task["result"] == "success"


@pytest.mark.unit
class TestAgents:
    """Agent registration and listing."""

    async def test_register_agent_persists_to_db(self, storage: Storage) -> None:
        """Registering an agent stores it in the database."""
        await storage.register_agent("agent-1", "coder")
        agents = await storage.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "agent-1"
        assert agents[0]["block_name"] == "coder"
        assert agents[0]["status"] == "idle"

    async def test_list_agents_returns_registered(self, storage: Storage) -> None:
        """list_agents returns all registered agents."""
        await storage.register_agent("a1", "coder")
        await storage.register_agent("a2", "reviewer")
        await storage.register_agent("a3", "planner")
        agents = await storage.list_agents()
        assert len(agents) == 3
        ids = {a["agent_id"] for a in agents}
        assert ids == {"a1", "a2", "a3"}


@pytest.mark.unit
class TestMessages:
    """Message append and retrieval."""

    async def test_append_message_stores_in_order(self, storage: Storage) -> None:
        """Messages are stored and returned in insertion order."""
        await storage.append_message("agent-1", "user", "Hello")
        await storage.append_message("agent-1", "assistant", "Hi there")
        await storage.append_message("agent-1", "user", "Do task")
        messages = await storage.get_messages("agent-1")
        assert len(messages) == 3
        assert messages[0]["content"] == "Hello"
        assert messages[1]["content"] == "Hi there"
        assert messages[2]["content"] == "Do task"

    async def test_get_messages_returns_agent_messages(self, storage: Storage) -> None:
        """get_messages only returns messages for the specified agent."""
        await storage.append_message("agent-1", "user", "Msg for agent 1")
        await storage.append_message("agent-2", "user", "Msg for agent 2")
        msgs_1 = await storage.get_messages("agent-1")
        msgs_2 = await storage.get_messages("agent-2")
        assert len(msgs_1) == 1
        assert msgs_1[0]["content"] == "Msg for agent 1"
        assert len(msgs_2) == 1
        assert msgs_2[0]["content"] == "Msg for agent 2"


@pytest.mark.unit
class TestAudit:
    """Audit log operations."""

    async def test_log_audit_stores_event(self, storage: Storage) -> None:
        """log_audit persists an audit entry."""
        await storage.log_audit("task_created", agent_id="a1", details="Created task t1")
        entries = await storage.list_audit()
        assert len(entries) == 1
        assert entries[0]["action"] == "task_created"
        assert entries[0]["agent_id"] == "a1"
        assert entries[0]["details"] == "Created task t1"

    async def test_list_audit_returns_recent_first(self, storage: Storage) -> None:
        """Audit entries are returned most-recent first."""
        await storage.log_audit("first")
        await storage.log_audit("second")
        await storage.log_audit("third")
        entries = await storage.list_audit()
        assert entries[0]["action"] == "third"
        assert entries[2]["action"] == "first"

    async def test_list_audit_respects_limit(self, storage: Storage) -> None:
        """list_audit respects the limit parameter."""
        for i in range(10):
            await storage.log_audit(f"action_{i}")
        entries = await storage.list_audit(limit=3)
        assert len(entries) == 3


@pytest.mark.unit
class TestDecisions:
    """Decision logging operations."""

    async def test_log_decision_persists_to_db(self, storage: Storage) -> None:
        """log_decision stores a decision record in the database."""
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="Use SQLite over PostgreSQL",
                rationale="Simpler deployment, no server needed",
            )
        )
        decisions = await storage.list_decisions()
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "Use SQLite over PostgreSQL"
        assert decisions[0]["rationale"] == "Simpler deployment, no server needed"
        assert decisions[0]["task_id"] == "t1"
        assert decisions[0]["agent_id"] == "a1"
        assert decisions[0]["reversible"] == 1

    async def test_log_decision_with_alternatives(self, storage: Storage) -> None:
        """log_decision stores rejected alternatives as JSON."""
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="Use async/await",
                rationale="Better concurrency model",
                alternatives=["threading", "multiprocessing"],
            )
        )
        decisions = await storage.list_decisions()
        assert len(decisions) == 1
        import json

        alts = json.loads(decisions[0]["alternatives"])
        assert alts == ["threading", "multiprocessing"]

    async def test_list_decisions_returns_recent_first(self, storage: Storage) -> None:
        """Decisions are returned most-recent first."""
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="First decision",
                rationale="First reason",
            )
        )
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="Second decision",
                rationale="Second reason",
            )
        )
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="Third decision",
                rationale="Third reason",
            )
        )
        decisions = await storage.list_decisions()
        assert decisions[0]["decision"] == "Third decision"
        assert decisions[2]["decision"] == "First decision"

    async def test_list_decisions_filters_by_task_id(self, storage: Storage) -> None:
        """list_decisions with task_id returns only that task's decisions."""
        await storage.log_decision(
            DecisionRecord(
                task_id="t1",
                agent_id="a1",
                decision="Decision for t1",
                rationale="Reason for t1",
            )
        )
        await storage.log_decision(
            DecisionRecord(
                task_id="t2",
                agent_id="a2",
                decision="Decision for t2",
                rationale="Reason for t2",
            )
        )
        t1_decisions = await storage.list_decisions(task_id="t1")
        assert len(t1_decisions) == 1
        assert t1_decisions[0]["decision"] == "Decision for t1"

    async def test_list_decisions_respects_limit(self, storage: Storage) -> None:
        """list_decisions respects the limit parameter."""
        for i in range(10):
            await storage.log_decision(
                DecisionRecord(
                    task_id="t1",
                    agent_id="a1",
                    decision=f"Decision {i}",
                    rationale=f"Reason {i}",
                )
            )
        decisions = await storage.list_decisions(limit=3)
        assert len(decisions) == 3


@pytest.mark.unit
class TestPersistence:
    """Data survives close/reconnect cycles."""

    async def test_close_and_reconnect_preserves_data(self, tmp_path: Path) -> None:
        """Data persists after closing and reopening the database."""
        db_path = tmp_path / "persist.db"

        # Write data
        store = Storage(db_path)
        await store.connect()
        await store.create_task("t1", "Survive restart")
        await store.register_agent("a1", "coder")
        await store.append_message("a1", "user", "Remember me")
        await store.log_audit("started", agent_id="a1")
        await store.close()

        # Reconnect and verify
        store2 = Storage(db_path)
        await store2.connect()
        try:
            task = await store2.get_task("t1")
            assert task is not None
            assert task["description"] == "Survive restart"

            agents = await store2.list_agents()
            assert len(agents) == 1

            messages = await store2.get_messages("a1")
            assert len(messages) == 1
            assert messages[0]["content"] == "Remember me"

            audit = await store2.list_audit()
            assert len(audit) == 1
            assert audit[0]["action"] == "started"
        finally:
            await store2.close()


@pytest.mark.unit
class TestMessagePersistence:
    """Conversation messages persist across sessions (REQ-07.1)."""

    async def test_messages_persist_across_reconnect(self, tmp_path: Path) -> None:
        """Messages stored survive close and reopen of storage."""
        db_path = tmp_path / "persist_msg.db"

        store = Storage(db_path)
        await store.connect()
        await store.append_message("agent-x", "system", "You are helpful.")
        await store.append_message("agent-x", "user", "Hello")
        await store.append_message("agent-x", "assistant", "Hi there!")
        await store.append_message("agent-x", "user", "Do task")
        await store.append_message("agent-x", "assistant", "Done.")
        await store.close()

        # Reopen and verify full conversation history
        store2 = Storage(db_path)
        await store2.connect()
        try:
            messages = await store2.get_messages("agent-x")
            assert len(messages) == 5
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == "Hello"
            assert messages[4]["role"] == "assistant"
            assert messages[4]["content"] == "Done."
        finally:
            await store2.close()

    async def test_task_context_survives_close_reopen(self, tmp_path: Path) -> None:
        """Task + agent + messages can be retrieved after reconnect."""
        db_path = tmp_path / "persist_ctx.db"

        store = Storage(db_path)
        await store.connect()
        await store.create_task("task-1", "Build feature")
        await store.update_task("task-1", status="completed", assigned_agent="ag-1")
        await store.register_agent("ag-1", "coder")
        await store.update_agent("ag-1", token_input="1200", token_output="600")
        await store.append_message("ag-1", "user", "Build the feature")
        await store.append_message("ag-1", "assistant", "Done building.")
        await store.close()

        # Reopen and verify full context
        store2 = Storage(db_path)
        await store2.connect()
        try:
            task = await store2.get_task("task-1")
            assert task is not None
            assert task["status"] == "completed"
            assert task["assigned_agent"] == "ag-1"

            agents = await store2.list_agents()
            assert len(agents) == 1
            assert agents[0]["token_input"] == 1200
            assert agents[0]["token_output"] == 600

            messages = await store2.get_messages("ag-1")
            assert len(messages) == 2
            assert messages[0]["content"] == "Build the feature"
            assert messages[1]["content"] == "Done building."
        finally:
            await store2.close()


@pytest.mark.unit
class TestLearningsCategory:
    """Learning creation with categories."""

    async def test_add_learning_with_category(self, storage: Storage) -> None:
        """add_learning stores a learning with the correct category."""
        lid = await storage.add_learning(
            LearningRecord(
                category="pattern",
                content="Always validate inputs before processing",
                source_task_id="task-1",
            )
        )
        assert lid is not None
        learning = await storage.get_learning(lid)
        assert learning is not None
        assert learning["category"] == "pattern"
        assert learning["content"] == "Always validate inputs before processing"
        assert learning["confidence"] == pytest.approx(0.3)
        assert learning["source_task_id"] == "task-1"

    async def test_add_learning_all_categories(self, storage: Storage) -> None:
        """All four categories are accepted and stored."""
        categories = ["pattern", "anti_pattern", "tool_tip", "domain_knowledge"]
        for cat in categories:
            lid = await storage.add_learning(LearningRecord(category=cat, content=f"Test {cat}"))
            learning = await storage.get_learning(lid)
            assert learning["category"] == cat

    async def test_list_learnings_filters_by_category(self, storage: Storage) -> None:
        """list_learnings with category filter returns only matching."""
        await storage.add_learning(LearningRecord(category="pattern", content="Pattern 1"))
        await storage.add_learning(LearningRecord(category="tool_tip", content="Tip 1"))
        patterns = await storage.list_learnings(category="pattern")
        assert len(patterns) == 1
        assert patterns[0]["category"] == "pattern"


@pytest.mark.unit
class TestLearningsConfidence:
    """Confidence scoring for learnings."""

    async def test_validate_increases_confidence(self, storage: Storage) -> None:
        """validate_learning increases confidence by 0.1."""
        lid = await storage.add_learning(LearningRecord(category="pattern", content="Test"))
        await storage.validate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.4)
        assert learning["validation_count"] == 1
        assert learning["last_validated"] is not None

    async def test_invalidate_decreases_confidence(self, storage: Storage) -> None:
        """invalidate_learning decreases confidence by 0.15."""
        lid = await storage.add_learning(LearningRecord(category="pattern", content="Test"))
        await storage.invalidate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.15)

    async def test_confidence_capped_at_1(self, storage: Storage) -> None:
        """Confidence never exceeds 1.0 after multiple validations."""
        lid = await storage.add_learning(
            LearningRecord(category="pattern", content="Test", confidence=0.95)
        )
        await storage.validate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(1.0)
        # Validate again — should still be 1.0
        await storage.validate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(1.0)

    async def test_confidence_floored_at_0(self, storage: Storage) -> None:
        """Confidence never goes below 0.0 after multiple invalidations."""
        lid = await storage.add_learning(
            LearningRecord(category="pattern", content="Test", confidence=0.1)
        )
        await storage.invalidate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.0)
        # Invalidate again — should still be 0.0
        await storage.invalidate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.0)

    async def test_confidence_caps_at_1_after_many_validates(self, storage: Storage) -> None:
        """Repeated validate_learning calls never push confidence above 1.0."""
        lid = await storage.add_learning(
            LearningRecord(category="pattern", content="Solid insight")
        )
        # Start at 0.3, validate 10 times (would be 1.3 without cap)
        for _ in range(10):
            await storage.validate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(1.0)
        assert learning["validation_count"] == 10

    async def test_confidence_floors_at_0_after_many_invalidates(self, storage: Storage) -> None:
        """Repeated invalidate_learning calls never push confidence below 0.0."""
        lid = await storage.add_learning(
            LearningRecord(category="anti_pattern", content="Bad habit")
        )
        # Start at 0.3, invalidate 10 times (would be -1.2 without floor)
        for _ in range(10):
            await storage.invalidate_learning(lid)
        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.0)


@pytest.mark.unit
class TestLearningsDecay:
    """Learning decay for old unvalidated entries."""

    async def test_decay_reduces_old_unvalidated_learnings(self, storage: Storage) -> None:
        """decay_learnings reduces confidence for old entries."""
        # Insert a learning with an old created_at timestamp
        assert storage._db is not None
        old_date = "2020-01-01T00:00:00+00:00"
        await storage._db.execute(
            "INSERT INTO learnings"
            " (category, content, confidence, created_at, last_validated)"
            " VALUES (?, ?, ?, ?, ?)",
            ("pattern", "Old learning", 0.5, old_date, None),
        )
        await storage._db.commit()

        count = await storage.decay_learnings(days_since_validation=30)
        assert count == 1

        entries = await storage.list_learnings()
        assert len(entries) == 1
        assert entries[0]["confidence"] == pytest.approx(0.45)

    async def test_decay_skips_recently_validated(self, storage: Storage) -> None:
        """decay_learnings does not touch recently validated entries."""
        lid = await storage.add_learning(LearningRecord(category="pattern", content="Fresh"))
        await storage.validate_learning(lid)

        count = await storage.decay_learnings(days_since_validation=30)
        assert count == 0

        learning = await storage.get_learning(lid)
        assert learning["confidence"] == pytest.approx(0.4)


@pytest.mark.unit
class TestStorageNotConnected:
    """Every public method raises RuntimeError when called before connect()."""

    @pytest.mark.parametrize(
        "method, args",
        [
            # Tasks
            ("create_task", ("t1", "desc")),
            ("get_task", ("t1",)),
            ("list_tasks", ()),
            ("update_task", ("t1",)),
            # Agents
            ("register_agent", ("a1", "coder")),
            ("list_agents", ()),
            ("update_agent", ("a1",)),
            # Messages
            ("append_message", ("a1", "user", "hi")),
            ("get_messages", ("a1",)),
            # Audit
            ("log_audit", ("action",)),
            ("list_audit", ()),
            # Decisions
            ("log_decision", (DecisionRecord(decision="dec", rationale="rat"),)),
            ("list_decisions", ()),
            # Learnings
            ("add_learning", (LearningRecord(category="pattern", content="content"),)),
            ("list_learnings", ()),
            ("validate_learning", (1,)),
            ("invalidate_learning", (1,)),
            ("decay_learnings", ()),
            ("delete_learning", (1,)),
            ("get_learning", (1,)),
            # Token summary
            ("get_token_summary", ()),
            # Questions
            (
                "insert_question",
                (
                    QuestionRecord(
                        question_id="q1",
                        question="why?",
                        context="ctx",
                        created_at="2024-01-01T00:00:00",
                    ),
                ),
            ),
            ("list_questions", ()),
            ("get_question", ("q1",)),
            ("answer_question", ("q1", "because")),
            # Checkpoints
            ("save_checkpoint", ("a1", None, "{}")),
            ("load_checkpoint", ("a1",)),
            # Memories
            ("add_memory", ("summary", "content", "category")),
            ("get_memory", ("m1",)),
            ("list_memory_summaries", ()),
            ("verify_memory", ("m1",)),
            ("consolidate_memories", ()),
            # Private helpers with guards
            ("_remove_stale_memories", (30,)),
            ("_dedup_memories", ()),
            # Eval results
            (
                "store_eval_result",
                (
                    {
                        "task_name": "t",
                        "model": "m",
                        "config_hash": "h",
                        "task_completed": 1,
                        "duration_seconds": 1.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "tool_calls": 0,
                        "turns": 0,
                        "error": None,
                        "timestamp": "2024-01-01T00:00:00",
                    },
                ),
            ),
            ("list_eval_results", ()),
            # Internal helper
            ("_get_tables", ()),
        ],
        ids=[
            "create_task",
            "get_task",
            "list_tasks",
            "update_task",
            "register_agent",
            "list_agents",
            "update_agent",
            "append_message",
            "get_messages",
            "log_audit",
            "list_audit",
            "log_decision",
            "list_decisions",
            "add_learning",
            "list_learnings",
            "validate_learning",
            "invalidate_learning",
            "decay_learnings",
            "delete_learning",
            "get_learning",
            "get_token_summary",
            "insert_question",
            "list_questions",
            "get_question",
            "answer_question",
            "save_checkpoint",
            "load_checkpoint",
            "add_memory",
            "get_memory",
            "list_memory_summaries",
            "verify_memory",
            "consolidate_memories",
            "_remove_stale_memories",
            "_dedup_memories",
            "store_eval_result",
            "list_eval_results",
            "_get_tables",
        ],
    )
    async def test_method_raises_when_not_connected(self, method: str, args: tuple) -> None:
        """Calling a method before connect() raises RuntimeError."""
        store = Storage(":memory:")
        with pytest.raises(RuntimeError, match="Storage not connected"):
            await getattr(store, method)(*args)


# ======================================================================
# Storage edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestStorageEdgeCases:
    """Cover storage update edge cases."""

    async def test_update_task_no_fields(self, tmp_path: Path) -> None:
        """update_task with no fields returns early (line 212)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test")
        # Call with no fields -- should return immediately
        await store.update_task("t1")
        # Task should be unchanged
        task = await store.get_task("t1")
        assert task is not None
        assert task["status"] == "pending"
        await store.close()

    async def test_update_task_invalid_fields(self, tmp_path: Path) -> None:
        """update_task with unrecognized fields returns early (line 216)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test")
        # Call with invalid field names -- filtered set is empty
        await store.update_task("t1", invalid_field="value", another="nope")
        task = await store.get_task("t1")
        assert task is not None
        assert task["status"] == "pending"
        await store.close()

    async def test_update_agent_no_fields(self, tmp_path: Path) -> None:
        """update_agent with no fields returns early (line 248)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.register_agent("a1", "coder")
        await store.update_agent("a1")
        await store.close()

    async def test_update_agent_invalid_fields(self, tmp_path: Path) -> None:
        """update_agent with unrecognized fields returns early (line 252)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.register_agent("a1", "coder")
        await store.update_agent("a1", bad_field="nope")
        await store.close()

    async def test_list_questions_all(self, tmp_path: Path) -> None:
        """list_questions with answered=None returns all (line 526)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.insert_question(
            QuestionRecord(
                question_id="q1",
                question="What?",
                context="ctx",
                created_at="2024-01-01T00:00:00",
                agent_id="a1",
            )
        )
        questions = await store.list_questions(answered=None)
        assert len(questions) >= 1
        await store.close()

    async def test_close_when_not_connected(self, tmp_path: Path) -> None:
        """close() when db is None is a no-op (line 172->exit)."""
        store = Storage(tmp_path / "test.db")
        # Don\'t connect -- _db is None
        await store.close()  # Should not raise
