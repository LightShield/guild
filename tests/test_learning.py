"""Tests for core/learning.py — extraction, storage."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.integration

from guild.core.learning import extract_learnings
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(response_text: str):
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=LLMResponse(content=response_text))
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestExtractLearnings:
    async def test_extracts_from_completed_task(self, storage):
        # Set up a completed task with messages
        await storage.create_task("t1", "fix the bug")
        await storage.update_task("t1", status="done", assigned_agent="a1", result="Fixed it")
        await storage.register_agent("a1", "coder")
        await storage.append_message("a1", "user", "fix the bug")
        await storage.append_message("a1", "assistant", "I fixed it by changing X")

        provider = make_provider(
            '{"category": "pattern", "content": "Check X before Y", "confidence": 0.8}\n'
            '{"category": "anti_pattern", "content": "Dont do Z", "confidence": 0.6}\n'
        )
        learnings = await extract_learnings("t1", storage, provider)
        assert len(learnings) == 2
        assert learnings[0]["category"] == "pattern"
        assert learnings[1]["confidence"] == 0.6

        # Verify stored in DB
        stored = await storage.list_learnings()
        assert len(stored) == 2

    async def test_no_task_returns_empty(self, storage):
        provider = make_provider("")
        result = await extract_learnings("nonexistent", storage, provider)
        assert result == []

    async def test_no_messages_returns_empty(self, storage):
        await storage.create_task("t1", "empty task")
        provider = make_provider("")
        result = await extract_learnings("t1", storage, provider)
        assert result == []

    async def test_malformed_json_skipped(self, storage):
        await storage.create_task("t1", "task")
        await storage.update_task("t1", status="done", assigned_agent="a1")
        await storage.register_agent("a1", "coder")
        await storage.append_message("a1", "user", "do thing")

        provider = make_provider(
            'Some preamble text\n'
            '{"category": "pattern", "content": "good insight", "confidence": 0.9}\n'
            'not json at all\n'
            '{"broken json\n'
        )
        learnings = await extract_learnings("t1", storage, provider)
        assert len(learnings) == 1
        assert learnings[0]["content"] == "good insight"
