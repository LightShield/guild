"""Tests for autonomy timeout (REQ-06.8)."""

import asyncio
import time

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.agent import AgentLoop, ToolResult
from guild.core.models import BlockDef, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


class TestAutonomyTimeout:
    """REQ-06.8: Configurable autonomy timeout."""

    async def test_timeout_stops_agent(self, storage):
        """Agent should stop after timeout_seconds even if not done."""
        call_count = 0

        async def slow_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.3)
            return LLMResponse(content="still working", tool_calls=[
                {"id": f"c{call_count}", "function": {
                    "name": "file_read",
                    "arguments": {"path": f"/tmp/file_{call_count}"},
                }}
            ])

        provider = AsyncMock()
        provider.generate = slow_generate
        provider.health_check = AsyncMock(return_value=True)

        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop(
            "a1", block, provider, storage,
            permission_checker=checker, timeout_seconds=1,
        )
        await agent.initialize()

        start = time.monotonic()
        result = await agent.run("work forever", max_turns=100)
        elapsed = time.monotonic() - start

        assert elapsed < 5
        assert agent.timed_out is True

    async def test_no_timeout_by_default(self, storage):
        """Without timeout, agent runs to completion normally."""
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=LLMResponse(content="done"))
        provider.health_check = AsyncMock(return_value=True)

        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()
        result = await agent.run("hi")
        assert result == "done"
        assert agent.timed_out is False

    async def test_timeout_zero_means_no_timeout(self, storage):
        """timeout_seconds=0 or None means no timeout."""
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=LLMResponse(content="done"))

        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage, timeout_seconds=0)
        await agent.initialize()
        result = await agent.run("hi")
        assert result == "done"
        assert agent.timed_out is False
