"""Tests for team execution via CLI (REQ-04, REQ-05)."""

import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.integration

from guild.blocks.registry import BlockRegistry, BUILTIN_TEAMS
from guild.core.models import PermissionTier
from guild.core.storage import Storage
from guild.core.team_runner import TeamRunner
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    """Create a test storage instance."""
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(responses: list[str]) -> AsyncMock:
    """Create a mock provider returning text responses."""
    provider = AsyncMock()
    resps = [LLMResponse(content=r, input_tokens=10, output_tokens=5) for r in responses]
    provider.generate = AsyncMock(side_effect=resps)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestTeamExecution:
    """REQ-04: Team execution end-to-end with mocked LLM."""

    async def test_dev_loop_runs_all_blocks(self, storage):
        """dev-loop should run planner, coder, tester, reviewer in order."""
        team = BUILTIN_TEAMS["dev-loop"]
        registry = BlockRegistry()
        # Need responses for: planner, coder, tester, reviewer
        provider = make_provider([
            "Plan: 1. Write hello.py 2. Add tests",
            "def hello(): return 'hello'",
            "All tests pass. Coverage 100%.",
            '{"pass": true, "score": 95, "feedback": "LGTM"}',
        ])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir="/tmp",
            permission_tier=PermissionTier.AUTOPILOT,
        )
        result = await runner.run("Write a hello world function")
        assert result  # Should have some output
        assert provider.generate.call_count == 4  # One per block

    async def test_verified_coder_with_retry(self, storage):
        """verified-coder should retry when evaluator fails."""
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        provider = make_provider([
            "def hello(): pass  # incomplete",
            '{"pass": false, "score": 30, "feedback": "Missing return value"}',
            "def hello(): return 'hello world'",
            '{"pass": true, "score": 90, "feedback": "Good"}',
        ])
        runner = TeamRunner(
            team, registry, provider, storage,
            permission_tier=PermissionTier.AUTOPILOT,
        )
        result = await runner.run("Write hello world")
        assert provider.generate.call_count == 4  # coder, eval(fail), coder(retry), eval(pass)

    async def test_team_tracks_total_tokens(self, storage):
        """Team runner should accumulate tokens from all blocks."""
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        provider = make_provider([
            "code",
            '{"pass": true, "score": 90}',
        ])
        runner = TeamRunner(
            team, registry, provider, storage,
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("task")
        assert runner.total_tokens["input"] == 20  # 10 per block * 2
        assert runner.total_tokens["output"] == 10  # 5 per block * 2

    async def test_team_creates_agents_in_storage(self, storage):
        """Each block execution should register an agent in storage."""
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        provider = make_provider([
            "code",
            '{"pass": true, "score": 90}',
        ])
        runner = TeamRunner(
            team, registry, provider, storage,
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("task")
        agents = await storage.list_agents()
        assert len(agents) >= 2  # coder + evaluator
