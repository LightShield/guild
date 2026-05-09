"""Tests for orchestration/spawner.py — agent spawning (REQ-04.3/04.4/04.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from guild.orchestration.bus import MessageBus
from guild.orchestration.spawner import AgentSpawner
from guild.provider.base import LLMResponse
from guild.tools.base import TOOL_SCHEMAS


def _make_provider(response_text: str = "Task complete.") -> AsyncMock:
    """Create a mock LLM provider that returns a fixed response."""
    provider = AsyncMock()
    provider.generate.return_value = LLMResponse(
        content=response_text,
        tool_calls=None,
        input_tokens=10,
        output_tokens=5,
        model="mock-model",
    )
    return provider


@pytest.mark.unit
@pytest.mark.req("REQ-04.3")
class TestSpawnCreatesAgent:
    """AgentSpawner.spawn() creates and tracks new agents."""

    async def test_spawn_creates_new_agent(self) -> None:
        """spawn() registers the agent in the active agents list."""
        provider = _make_provider()
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        await spawner.spawn(task="Write a haiku", agent_id="test-agent-1")
        assert "test-agent-1" in spawner.active_agents

    async def test_spawn_returns_agent_result(self) -> None:
        """spawn() returns the final text output from the sub-agent."""
        provider = _make_provider("The answer is 42.")
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        result = await spawner.spawn(task="What is the answer?")
        assert result == "The answer is 42."


@pytest.mark.unit
@pytest.mark.req("REQ-04.4")
class TestSpawnAgentToolSchema:
    """The spawn_agent tool is registered in TOOL_SCHEMAS."""

    def test_spawn_agent_tool_schema_exists(self) -> None:
        """spawn_agent appears in TOOL_SCHEMAS with correct structure."""
        assert "spawn_agent" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["spawn_agent"]
        assert schema["name"] == "spawn_agent"
        params = schema["parameters"]
        assert "task" in params["properties"]
        assert "task" in params["required"]


@pytest.mark.unit
@pytest.mark.req("REQ-04.5")
class TestSpawnedAgentExecution:
    """Spawned agents execute tasks and can coexist."""

    async def test_spawned_agent_executes_task(self) -> None:
        """The sub-agent calls the provider with the given task."""
        provider = _make_provider("Done!")
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        result = await spawner.spawn(task="Do something useful")
        assert result == "Done!"
        # Verify the provider was called
        provider.generate.assert_called()
        # The user message should contain the task
        call_args = provider.generate.call_args
        messages = call_args[0][0]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any("Do something useful" in m["content"] for m in user_msgs)

    async def test_multiple_agents_can_be_active(self) -> None:
        """Multiple agents can be spawned and tracked simultaneously."""
        provider = _make_provider("Result")
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        await spawner.spawn(task="Task A", agent_id="worker-1")
        await spawner.spawn(task="Task B", agent_id="worker-2")
        await spawner.spawn(task="Task C", agent_id="worker-3")

        assert len(spawner.active_agents) == 3
        assert "worker-1" in spawner.active_agents
        assert "worker-2" in spawner.active_agents
        assert "worker-3" in spawner.active_agents

    async def test_get_agent_returns_loop(self) -> None:
        """get_agent() returns the AgentLoop for a spawned agent."""
        provider = _make_provider()
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        await spawner.spawn(task="Test", agent_id="a1")
        agent = spawner.get_agent("a1")
        assert agent is not None

    async def test_get_agent_returns_none_for_unknown(self) -> None:
        """get_agent() returns None for unknown agent IDs."""
        provider = _make_provider()
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        assert spawner.get_agent("nonexistent") is None

    async def test_execute_spawn_success(self) -> None:
        """execute_spawn() executes spawn and returns ToolResult."""
        provider = _make_provider("Sub-agent done.")
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        result = await spawner.execute_spawn({"task": "Sub-task"}, None)
        assert result.success is True
        assert result.output == "Sub-agent done."

    async def test_execute_spawn_missing_task(self) -> None:
        """execute_spawn() returns error if task is missing."""
        provider = _make_provider()
        bus = MessageBus()
        spawner = AgentSpawner(provider=provider, storage=None, bus=bus)

        result = await spawner.execute_spawn({}, None)
        assert result.success is False
        assert "task" in (result.error or "").lower()
