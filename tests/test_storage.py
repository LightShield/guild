"""Tests for core/storage.py — CRUD operations, schema creation."""

import pytest

pytestmark = pytest.mark.integration
from pathlib import Path

from guild.core.storage import Storage


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


class TestStorageConnection:
    async def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "new.db"
        s = Storage(db_path)
        await s.connect()
        assert db_path.exists()
        await s.close()

    async def test_wal_mode(self, storage):
        async with storage.db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
            assert row[0] == "wal"

    async def test_tables_created(self, storage):
        async with storage.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            tables = {row[0] for row in await cur.fetchall()}
        assert {"tasks", "agents", "messages", "audit_log", "learnings"} <= tables


class TestTaskCRUD:
    async def test_create_and_get(self, storage):
        await storage.create_task("t1", "fix bug")
        task = await storage.get_task("t1")
        assert task is not None
        assert task["description"] == "fix bug"
        assert task["status"] == "pending"

    async def test_get_nonexistent(self, storage):
        assert await storage.get_task("nope") is None

    async def test_list_tasks(self, storage):
        await storage.create_task("t1", "task one")
        await storage.create_task("t2", "task two")
        tasks = await storage.list_tasks()
        assert len(tasks) == 2

    async def test_list_tasks_by_status(self, storage):
        await storage.create_task("t1", "task one")
        await storage.update_task("t1", status="done")
        await storage.create_task("t2", "task two")
        done = await storage.list_tasks(status="done")
        assert len(done) == 1
        assert done[0]["task_id"] == "t1"

    async def test_update_task(self, storage):
        await storage.create_task("t1", "fix bug")
        await storage.update_task("t1", status="in_progress", assigned_agent="a1")
        task = await storage.get_task("t1")
        assert task["status"] == "in_progress"
        assert task["assigned_agent"] == "a1"


class TestAgentCRUD:
    async def test_register_and_list(self, storage):
        await storage.register_agent("a1", "coder")
        agents = await storage.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "a1"
        assert agents[0]["block_name"] == "coder"
        assert agents[0]["status"] == "idle"

    async def test_update_agent(self, storage):
        await storage.register_agent("a1", "coder")
        await storage.update_agent("a1", status="running")
        agents = await storage.list_agents()
        assert agents[0]["status"] == "running"


class TestMessageCRUD:
    async def test_append_and_get(self, storage):
        await storage.register_agent("a1", "coder")
        await storage.append_message("a1", "user", "hello")
        await storage.append_message("a1", "assistant", "hi there")
        msgs = await storage.get_messages("a1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "hi there"

    async def test_messages_isolated_per_agent(self, storage):
        await storage.register_agent("a1", "coder")
        await storage.register_agent("a2", "reviewer")
        await storage.append_message("a1", "user", "for a1")
        await storage.append_message("a2", "user", "for a2")
        assert len(await storage.get_messages("a1")) == 1
        assert len(await storage.get_messages("a2")) == 1


class TestAuditLog:
    async def test_log_audit(self, storage):
        await storage.log_audit("test_action", agent_id="a1", details="some details")
        async with storage.db.execute("SELECT * FROM audit_log") as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1


class TestLearnings:
    async def test_add_and_list(self, storage):
        await storage.add_learning("pattern", "use TDD", confidence=0.8, source_task_id="t1")
        items = await storage.list_learnings()
        assert len(items) == 1
        assert items[0]["category"] == "pattern"
        assert items[0]["confidence"] == 0.8

    async def test_filter_by_confidence(self, storage):
        await storage.add_learning("pattern", "good thing", confidence=0.9)
        await storage.add_learning("anti_pattern", "bad thing", confidence=0.3)
        high = await storage.list_learnings(min_confidence=0.5)
        assert len(high) == 1
        assert high[0]["content"] == "good thing"
