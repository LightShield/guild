"""Tests for storage/sqlite.py — SQLite persistence layer (REQ-06.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.storage.sqlite import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
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
@pytest.mark.req("REQ-06.6")
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
@pytest.mark.req("REQ-06.6")
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
@pytest.mark.req("REQ-06.6")
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
@pytest.mark.req("REQ-06.6")
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
@pytest.mark.req("REQ-06.6")
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
