"""Tests for stuck detection integration with agent loop (REQ-06.3, REQ-06.4)."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.agent import AgentLoop
from guild.core.models import BlockDef, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    """Create a test storage instance."""
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(responses: list[LLMResponse]) -> AsyncMock:
    """Create a mock provider returning responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=responses)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestStuckIntegration:
    """REQ-06.3, REQ-06.4: Agent loop should detect stuck and stop."""

    async def test_agent_stops_on_repeated_tool_errors(self, storage):
        """Agent should stop if the same tool error repeats."""
        # Agent calls file_read 3 times on a nonexistent file
        provider = make_provider([
            LLMResponse(content="", tool_calls=[
                {"id": "c0", "function": {"name": "file_read", "arguments": {"path": "/nonexistent"}}}
            ]),
            LLMResponse(content="", tool_calls=[
                {"id": "c1", "function": {"name": "file_read", "arguments": {"path": "/nonexistent"}}}
            ]),
            LLMResponse(content="", tool_calls=[
                {"id": "c2", "function": {"name": "file_read", "arguments": {"path": "/nonexistent"}}}
            ]),
            LLMResponse(content="I give up"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop(
            "a1", block, provider, storage,
            permission_checker=checker, enable_stuck_detection=True,
        )
        await agent.initialize()
        result = await agent.run("read /nonexistent")

        # Should have stopped early due to stuck detection
        # The result should mention being stuck
        assert agent.stuck_reason != ""

    async def test_agent_not_stuck_with_varied_calls(self, storage):
        """Agent making different calls should not trigger stuck detection."""
        provider = make_provider([
            LLMResponse(content="", tool_calls=[
                {"id": "c0", "function": {"name": "file_read", "arguments": {"path": "/tmp/a"}}}
            ]),
            LLMResponse(content="", tool_calls=[
                {"id": "c1", "function": {"name": "file_read", "arguments": {"path": "/tmp/b"}}}
            ]),
            LLMResponse(content="Done reading both files"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop(
            "a1", block, provider, storage,
            permission_checker=checker, enable_stuck_detection=True,
        )
        await agent.initialize()
        result = await agent.run("read files")
        assert agent.stuck_reason == ""
        assert result == "Done reading both files"

    async def test_stuck_detection_disabled_by_default(self, storage):
        """Without enable_stuck_detection, agent should not check for stuck."""
        provider = make_provider([
            LLMResponse(content="", tool_calls=[
                {"id": "c0", "function": {"name": "file_read", "arguments": {"path": "/x"}}}
            ]),
            LLMResponse(content="", tool_calls=[
                {"id": "c1", "function": {"name": "file_read", "arguments": {"path": "/x"}}}
            ]),
            LLMResponse(content="", tool_calls=[
                {"id": "c2", "function": {"name": "file_read", "arguments": {"path": "/x"}}}
            ]),
            LLMResponse(content="still going"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop("a1", block, provider, storage, permission_checker=checker)
        await agent.initialize()
        result = await agent.run("do it", max_turns=4)
        # Should have run all 4 turns without stopping
        assert provider.generate.call_count == 4
