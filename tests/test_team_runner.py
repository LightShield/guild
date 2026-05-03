"""Tests for core/team_runner.py — execution order, loop handling, error propagation."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.blocks.registry import BlockRegistry, TeamDef, Connection, LoopDef, BUILTIN_TEAMS
from guild.core.models import PermissionTier
from guild.core.storage import Storage
from guild.core.team_runner import TeamRunner
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(responses: list[str]):
    """Mock provider that returns text responses in sequence."""
    provider = AsyncMock()
    resps = [LLMResponse(content=r, input_tokens=10, output_tokens=5) for r in responses]
    provider.generate = AsyncMock(side_effect=resps)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestExecutionOrder:
    async def test_linear_chain(self, storage):
        """research → planner → coder should execute in that order."""
        team = BUILTIN_TEAMS["research-and-implement"]
        registry = BlockRegistry()

        # Need enough responses for 3 blocks
        provider = make_provider(["research findings", "the plan", "the code"])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        order = runner._execution_order()
        assert order.index("researcher") < order.index("planner")
        assert order.index("planner") < order.index("coder")

    async def test_dev_loop_order(self, storage):
        """planner should come before coder, tester, reviewer."""
        team = BUILTIN_TEAMS["dev-loop"]
        registry = BlockRegistry()
        provider = make_provider(["plan", "code", "tests pass", "review pass"])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        order = runner._execution_order()
        assert order[0] == "planner"


class TestLoopHandling:
    async def test_pass_exits_loop(self, storage):
        """If evaluator says pass, loop should exit."""
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        # coder produces code, evaluator passes
        provider = make_provider(["code v1", '{"pass": true, "score": 90, "feedback": "good"}'])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        result = await runner.run("write hello world")
        assert provider.generate.call_count == 2  # coder + evaluator, no retry

    async def test_fail_retries(self, storage):
        """If evaluator fails, generator should be re-run."""
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        # coder v1, evaluator fails, coder v2, evaluator passes
        provider = make_provider([
            "code v1",
            '{"pass": false, "score": 30, "feedback": "bad"}',
            "code v2",
            '{"pass": true, "score": 85, "feedback": "good"}',
        ])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        result = await runner.run("write hello world")
        assert provider.generate.call_count == 4

    async def test_max_iterations_stops_loop(self, storage):
        """Loop should stop after max_iterations even if evaluator never passes."""
        team = TeamDef(
            name="test-loop",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(source_block="coder", source_port="changes", target_block="evaluator", target_port="artifact")],
            loops=[LoopDef(evaluator_block="evaluator", generator_block="coder", max_iterations=2)],
            entry_block="coder",
        )
        registry = BlockRegistry()
        # All evaluator responses fail
        provider = make_provider([
            "code v1", '{"pass": false, "score": 20}',
            "code v2", '{"pass": false, "score": 25}',
        ])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        await runner.run("write something")
        # Should have: coder, eval, coder(retry), eval — 4 calls, then stop
        assert provider.generate.call_count == 4


class TestCheckPass:
    def test_json_pass_true(self):
        assert TeamRunner._check_pass_from_text('{"pass": true, "score": 90}') is True

    def test_json_pass_false(self):
        assert TeamRunner._check_pass_from_text('{"pass": false, "score": 30}') is False

    def test_score_threshold(self):
        assert TeamRunner._check_pass_from_text('{"score": 80}') is True
        assert TeamRunner._check_pass_from_text('{"score": 50}') is False

    def test_heuristic_pass(self):
        assert TeamRunner._check_pass_from_text("The code looks good. Pass.") is True

    def test_heuristic_lgtm(self):
        assert TeamRunner._check_pass_from_text("LGTM, approved.") is True

    def test_heuristic_fail(self):
        assert TeamRunner._check_pass_from_text("This needs more work.") is False


class TestTokenTracking:
    async def test_tokens_accumulated(self, storage):
        team = BUILTIN_TEAMS["verified-coder"]
        registry = BlockRegistry()
        provider = make_provider(["code", '{"pass": true, "score": 90}'])
        runner = TeamRunner(team, registry, provider, storage, permission_tier=PermissionTier.AUTOPILOT)
        await runner.run("task")
        assert runner.total_tokens["input"] > 0
        assert runner.total_tokens["output"] > 0
