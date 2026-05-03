"""Tests for learning confidence scoring and validation (REQ-09.3)."""

import pytest

pytestmark = pytest.mark.integration

from guild.core.storage import Storage


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


class TestLearningConfidence:
    """REQ-09.3: Learnings start tentative, promoted after validation."""

    async def test_new_learning_starts_at_given_confidence(self, storage):
        await storage.add_learning("pattern", "use TDD", confidence=0.5)
        items = await storage.list_learnings()
        assert items[0]["confidence"] == 0.5

    async def test_validate_learning_increases_confidence(self, storage):
        await storage.add_learning("pattern", "use TDD", confidence=0.5)
        items = await storage.list_learnings()
        learning_id = items[0]["id"]

        await storage.validate_learning(learning_id)
        items = await storage.list_learnings()
        assert items[0]["confidence"] > 0.5

    async def test_invalidate_learning_decreases_confidence(self, storage):
        await storage.add_learning("pattern", "bad idea", confidence=0.8)
        items = await storage.list_learnings()
        learning_id = items[0]["id"]

        await storage.invalidate_learning(learning_id)
        items = await storage.list_learnings()
        assert items[0]["confidence"] < 0.8

    async def test_confidence_capped_at_1(self, storage):
        await storage.add_learning("pattern", "great idea", confidence=0.95)
        items = await storage.list_learnings()
        learning_id = items[0]["id"]

        await storage.validate_learning(learning_id)
        await storage.validate_learning(learning_id)
        items = await storage.list_learnings()
        assert items[0]["confidence"] <= 1.0

    async def test_confidence_floored_at_0(self, storage):
        await storage.add_learning("pattern", "terrible idea", confidence=0.1)
        items = await storage.list_learnings()
        learning_id = items[0]["id"]

        await storage.invalidate_learning(learning_id)
        await storage.invalidate_learning(learning_id)
        items = await storage.list_learnings()
        assert items[0]["confidence"] >= 0.0
