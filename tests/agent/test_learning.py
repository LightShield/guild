"""Tests for agent/learning.py — post-task learning extraction (REQ-09)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.agent.learning import (
    extract_learnings,
    format_learnings_for_injection,
)
from guild.provider.base import LLMResponse
from guild.storage.sqlite import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Create a mock LLMProvider."""
    provider = AsyncMock()
    provider.generate = AsyncMock()
    return provider


async def _setup_task_with_messages(storage: Storage, task_id: str = "task-1") -> str:
    """Create a task with assigned agent and messages. Returns agent_id."""
    agent_id = f"agent-{task_id}"
    await storage.create_task(task_id, "Test task description")
    await storage.update_task(task_id, status="completed", assigned_agent=agent_id)
    await storage.register_agent(agent_id, "coder")
    await storage.append_message(agent_id, "user", "Write a hello world function")
    await storage.append_message(agent_id, "assistant", "I'll write that for you.")
    await storage.append_message(agent_id, "tool", "File written successfully")
    await storage.append_message(agent_id, "assistant", "Done! Created hello.py")
    return agent_id


@pytest.mark.unit
@pytest.mark.req("REQ-09.1")
class TestExtractLearnings:
    """Post-task learning extraction."""

    async def test_extract_learnings_calls_provider(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings calls the LLM provider with learner prompt."""
        await _setup_task_with_messages(storage)
        mock_provider.generate.return_value = LLMResponse(content="", model="test")

        await extract_learnings("task-1", storage, mock_provider)

        mock_provider.generate.assert_called_once()
        call_messages = mock_provider.generate.call_args[0][0]
        assert call_messages[0]["role"] == "system"
        assert "JSON lines" in call_messages[0]["content"]

    async def test_extract_learnings_parses_json_lines(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings correctly parses valid JSON lines from LLM."""
        await _setup_task_with_messages(storage)
        response_content = (
            '{"category": "pattern", "content": "Use early returns"}\n'
            '{"category": "tool_tip", "content": "file_read is fast"}\n'
        )
        mock_provider.generate.return_value = LLMResponse(
            content=response_content, model="test"
        )

        result = await extract_learnings("task-1", storage, mock_provider)

        assert len(result) == 2
        assert result[0]["category"] == "pattern"
        assert result[0]["content"] == "Use early returns"
        assert result[1]["category"] == "tool_tip"

    async def test_extract_learnings_stores_in_db(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings stores parsed learnings in the database."""
        await _setup_task_with_messages(storage)
        response_content = (
            '{"category": "pattern", "content": "Validate early"}\n'
        )
        mock_provider.generate.return_value = LLMResponse(
            content=response_content, model="test"
        )

        await extract_learnings("task-1", storage, mock_provider)

        learnings = await storage.list_learnings()
        assert len(learnings) == 1
        assert learnings[0]["content"] == "Validate early"
        assert learnings[0]["source_task_id"] == "task-1"
        assert learnings[0]["confidence"] == pytest.approx(0.3)

    async def test_extract_learnings_skips_invalid_lines(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings skips malformed JSON and invalid categories."""
        await _setup_task_with_messages(storage)
        response_content = (
            "not json at all\n"
            '{"category": "invalid_cat", "content": "bad category"}\n'
            '{"category": "pattern"}\n'  # missing content
            '{"category": "pattern", "content": "Valid one"}\n'
            "another garbage line\n"
        )
        mock_provider.generate.return_value = LLMResponse(
            content=response_content, model="test"
        )

        result = await extract_learnings("task-1", storage, mock_provider)

        assert len(result) == 1
        assert result[0]["content"] == "Valid one"

    async def test_extract_learnings_no_task(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings returns empty list for nonexistent task."""
        result = await extract_learnings("nonexistent", storage, mock_provider)
        assert result == []
        mock_provider.generate.assert_not_called()

    async def test_extract_learnings_no_agent(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """extract_learnings returns empty list if task has no assigned agent."""
        await storage.create_task("task-2", "Unassigned task")
        result = await extract_learnings("task-2", storage, mock_provider)
        assert result == []
        mock_provider.generate.assert_not_called()


@pytest.mark.unit
@pytest.mark.req("REQ-09.4")
class TestFormatLearningsForInjection:
    """Learning injection into agent prompts."""

    def test_format_learnings_for_injection(self) -> None:
        """format_learnings_for_injection produces readable text."""
        learnings = [
            {"category": "pattern", "content": "Use early returns", "confidence": 0.8},
            {"category": "tool_tip", "content": "grep is fast", "confidence": 0.6},
        ]
        result = format_learnings_for_injection(learnings)
        assert "Learnings from previous tasks" in result
        assert "Use early returns" in result
        assert "grep is fast" in result
        assert "pattern" in result
        assert "0.8" in result

    def test_injection_filters_by_min_confidence(self) -> None:
        """format_learnings_for_injection excludes low-confidence items."""
        learnings = [
            {"category": "pattern", "content": "High conf", "confidence": 0.9},
            {"category": "pattern", "content": "Low conf", "confidence": 0.3},
            {"category": "pattern", "content": "Medium conf", "confidence": 0.4},
        ]
        result = format_learnings_for_injection(learnings)
        assert "High conf" in result
        assert "Low conf" not in result
        assert "Medium conf" not in result

    def test_injection_empty_when_no_eligible(self) -> None:
        """format_learnings_for_injection returns empty string when none qualify."""
        learnings = [
            {"category": "pattern", "content": "Too low", "confidence": 0.2},
        ]
        result = format_learnings_for_injection(learnings)
        assert result == ""

    def test_injection_respects_max_items(self) -> None:
        """format_learnings_for_injection limits output to max_items."""
        learnings = [
            {"category": "pattern", "content": f"Item {i}", "confidence": 0.9}
            for i in range(20)
        ]
        result = format_learnings_for_injection(learnings, max_items=5)
        # Should have exactly 5 learning items plus the header
        lines = [ln for ln in result.strip().splitlines() if ln.startswith("- [")]
        assert len(lines) == 5


@pytest.mark.unit
@pytest.mark.req("REQ-09.6")
class TestCrossTaskLearning:
    """Cross-task learning — patterns from task A inform task B."""

    async def test_learnings_from_task_a_available_to_task_b(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """Learnings extracted from task A are available for injection into task B."""
        # Setup and run extraction for task A
        await _setup_task_with_messages(storage, task_id="task-a")
        mock_provider.generate.return_value = LLMResponse(
            content='{"category": "pattern", "content": "Always check return values"}\n',
            model="test",
        )
        await extract_learnings("task-a", storage, mock_provider)

        # Boost confidence so it's injectable
        learnings = await storage.list_learnings()
        assert len(learnings) == 1
        lid = learnings[0]["id"]
        # Validate enough times to reach 0.5
        await storage.validate_learning(lid)  # 0.4
        await storage.validate_learning(lid)  # 0.5

        # Now fetch learnings as task B would — they should be available
        high_conf = await storage.list_learnings(min_confidence=0.5)
        assert len(high_conf) == 1
        assert high_conf[0]["content"] == "Always check return values"
        assert high_conf[0]["source_task_id"] == "task-a"

        # Format for injection
        injection = format_learnings_for_injection(high_conf)
        assert "Always check return values" in injection
