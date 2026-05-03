"""Tests for wiring — verify all modules are connected to the actual system."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.agent import AgentLoop, ToolResult, _check_shell_denylist, SHELL_DENYLIST
from guild.core.models import BlockDef, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.ratelimit import RateLimiter, ToolQueue
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


class TestShellDenylist:
    """REQ-13: Command denylist in shell tool."""

    def test_blocks_rm_rf_root(self):
        assert _check_shell_denylist("rm -rf /") is not None

    def test_blocks_git_force_push(self):
        assert _check_shell_denylist("git push --force") is not None

    def test_blocks_git_reset_hard(self):
        assert _check_shell_denylist("git reset --hard") is not None

    def test_allows_normal_commands(self):
        assert _check_shell_denylist("ls -la") is None
        assert _check_shell_denylist("echo hello") is None
        assert _check_shell_denylist("python3 test.py") is None
        assert _check_shell_denylist("git status") is None
        assert _check_shell_denylist("git add .") is None

    def test_blocks_mkfs(self):
        assert _check_shell_denylist("mkfs.ext4 /dev/sda") is not None

    async def test_shell_tool_enforces_denylist(self):
        from guild.core.agent import execute_tool
        result = await execute_tool("shell", {"command": "rm -rf /"})
        assert result.success is False
        assert "denylist" in (result.error or "").lower()


class TestMicroCompactWired:
    """Verify MicroCompact is used in AgentLoop when context_window > 0."""

    async def test_compression_active_with_context_window(self, storage):
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=LLMResponse(content="done"))

        block = BlockDef(name="test", role="test", system_prompt="sys", tools=[])
        agent = AgentLoop("a1", block, provider, storage, context_window=1000)
        await agent.initialize()
        assert agent._compactor is not None

    async def test_no_compression_without_context_window(self, storage):
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=LLMResponse(content="done"))

        block = BlockDef(name="test", role="test", system_prompt="sys", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()
        assert agent._compactor is None


class TestRateLimiterWired:
    """Verify RateLimiter is used in AgentLoop."""

    async def test_rate_limiter_called(self, storage):
        limiter = RateLimiter(max_calls=100, window_seconds=60)
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=LLMResponse(content="done"))

        block = BlockDef(name="test", role="test", system_prompt="sys", tools=[])
        agent = AgentLoop("a1", block, provider, storage, rate_limiter=limiter)
        await agent.initialize()
        await agent.run("hi")
        # After one LLM call, available should be 99
        assert limiter.available == 99


class TestToolQueueWired:
    """Verify ToolQueue is used in AgentLoop."""

    async def test_tool_queue_used(self, storage, tmp_path):
        queue = ToolQueue(max_concurrent=2)
        (tmp_path / "test.txt").write_text("content")

        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=[
            LLMResponse(content="", tool_calls=[
                {"id": "c0", "function": {"name": "file_read", "arguments": {"path": str(tmp_path / "test.txt")}}}
            ]),
            LLMResponse(content="done"),
        ])

        block = BlockDef(name="test", role="test", system_prompt="sys", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop(
            "a1", block, provider, storage,
            permission_checker=checker, tool_queue=queue,
        )
        await agent.initialize()
        result = await agent.run("read file")
        assert result == "done"
        assert queue.active_count == 0  # all done
