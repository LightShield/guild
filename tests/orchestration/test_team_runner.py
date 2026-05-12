"""Tests for orchestration/team_runner.py — team execution engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.blocks.definition import BlockDef, Connection, LoopDef, PortDef, TeamDef
from guild.blocks.registry import BlockRegistry
from guild.orchestration.team_runner import (
    AgentStatus,
    BlockError,
    DECISION_ESCALATE,
    DECISION_SKIP,
    EscalationError,
    EvaluatorResult,
    TeamRunner,
    _extract_embedded_json,
)
from guild.provider.base import LLMResponse

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_provider(*responses: LLMResponse) -> AsyncMock:
    """Create a mock provider returning responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=list(responses))
    return provider


def _make_team_with_entry() -> TeamDef:
    """Create a simple two-block team with an entry block."""
    return TeamDef(
        name="test-team",
        blocks={
            "orchestrator": "planner",
            "worker": "coder",
        },
        connections=[
            Connection(
                source_block="orchestrator",
                source_port="plan",
                target_block="worker",
                target_port="spec",
            ),
        ],
        entry_block="orchestrator",
    )


def _make_loop_team() -> TeamDef:
    """Create a team with a generator-evaluator loop."""
    return TeamDef(
        name="loop-team",
        blocks={
            "orchestrator": "planner",
            "gen": "coder",
            "eval": "evaluator",
        },
        connections=[
            Connection(
                source_block="orchestrator",
                source_port="plan",
                target_block="gen",
                target_port="spec",
            ),
        ],
        loops=[
            LoopDef(
                generator_block="gen",
                evaluator_block="eval",
                max_iterations=5,
            ),
        ],
        entry_block="orchestrator",
    )


def _make_parallel_team() -> TeamDef:
    """Create a team with parallel branches from entry."""
    return TeamDef(
        name="parallel-team",
        blocks={
            "orchestrator": "planner",
            "branch_a": "coder",
            "branch_b": "researcher",
        },
        connections=[
            Connection(
                source_block="orchestrator",
                source_port="plan",
                target_block="branch_a",
                target_port="spec",
            ),
            Connection(
                source_block="orchestrator",
                source_port="plan",
                target_block="branch_b",
                target_port="question",
            ),
        ],
        entry_block="orchestrator",
    )


def _registry_with_retries(max_retries: int = 1) -> BlockRegistry:
    """Create a registry where blocks have configurable retries."""
    registry = BlockRegistry()
    # Override coder to have more retries for testing
    coder = registry.get_block("coder")
    if coder:
        coder.max_retries = max_retries
    return registry


# ---------------------------------------------------------------------------
# Tests: Entry agent (REQ-04.1, REQ-04.2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEntryAgent:
    """Entry agent is always the orchestrator, first in execution."""

    async def test_entry_agent_is_first_in_execution(self) -> None:
        """The entry_block is always the first block in execution order."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider(
            # orchestrator response
            LLMResponse(content="Plan: implement feature X", tool_calls=None),
            # worker response
            LLMResponse(content="Done implementing.", tool_calls=None),
        )
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        assert order[0] == "orchestrator"

    async def test_entry_agent_first_even_with_complex_graph(self) -> None:
        """Entry block first even when graph has multiple roots."""
        team = TeamDef(
            name="complex",
            blocks={
                "orchestrator": "planner",
                "independent": "researcher",
                "downstream": "coder",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="downstream",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        assert order[0] == "orchestrator"


@pytest.mark.unit
class TestEntryAgentPresent:
    """Entry agent must be present in preset team compositions."""

    async def test_entry_agent_present_in_team(self) -> None:
        """The entry_block exists in the team's blocks dict."""
        team = _make_team_with_entry()
        assert team.entry_block in team.blocks

    async def test_entry_agent_in_execution_order(self) -> None:
        """Entry agent appears in the execution order."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        assert team.entry_block in order


# ---------------------------------------------------------------------------
# Tests: Agent lifecycle (REQ-04.9)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentLifecycle:
    """Agent lifecycle management — spawn, monitor, track status."""

    async def test_agent_lifecycle_tracked(self) -> None:
        """Agents transition through lifecycle states during execution."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider(
            LLMResponse(content="Plan ready", tool_calls=None),
            LLMResponse(content="Code done", tool_calls=None),
        )
        runner = TeamRunner(team, registry, provider)
        await runner.run("Build a feature")

        statuses = runner.agent_statuses
        assert statuses["orchestrator"] == AgentStatus.COMPLETED
        assert statuses["worker"] == AgentStatus.COMPLETED

    async def test_failed_agent_has_failed_status(self) -> None:
        """A block that fails all retries gets FAILED status."""
        team = TeamDef(
            name="fail-team",
            blocks={"orchestrator": "planner", "failing": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="failing",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                LLMResponse(content="Plan", tool_calls=None),
                RuntimeError("LLM unavailable"),
                RuntimeError("LLM unavailable"),
            ]
        )
        runner = TeamRunner(team, registry, provider)
        runner.set_caller_decision("failing", "skip")
        await runner.run("Do something")

        assert runner.agent_statuses["failing"] == AgentStatus.FAILED


# ---------------------------------------------------------------------------
# Tests: Evaluator result (REQ-04.40)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluatorResult:
    """Standard evaluator output: {pass, score, feedback}."""

    async def test_evaluator_result_structure(self) -> None:
        """EvaluatorResult has correct fields and types."""
        result = EvaluatorResult(passed=True, score=85, feedback="Good work")

        assert result.passed is True
        assert result.score == 85
        assert result.feedback == "Good work"
        assert result.details == {}

    async def test_evaluator_result_with_details(self) -> None:
        """EvaluatorResult can carry additional details."""
        result = EvaluatorResult(
            passed=False,
            score=40,
            feedback="Needs improvement",
            details={"issues": ["missing tests", "no docstring"]},
        )

        assert result.passed is False
        assert result.details["issues"] == ["missing tests", "no docstring"]

    async def test_parse_evaluator_json_output(self) -> None:
        """TeamRunner parses valid JSON evaluator output."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = '{"pass": true, "score": 92, "feedback": "Excellent code quality"}'
        result = runner._parse_evaluator_result(output)

        assert result.passed is True
        assert result.score == 92
        assert result.feedback == "Excellent code quality"

    async def test_parse_evaluator_json_with_passed_key(self) -> None:
        """Parser handles both 'pass' and 'passed' keys."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = '{"passed": false, "score": 30, "feedback": "Too many bugs"}'
        result = runner._parse_evaluator_result(output)

        assert result.passed is False
        assert result.score == 30

    async def test_parse_evaluator_embedded_json(self) -> None:
        """Parser extracts JSON embedded in surrounding text."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = 'Here is my evaluation:\n{"pass": true, "score": 75, "feedback": "OK"}\nEnd.'
        result = runner._parse_evaluator_result(output)

        assert result.passed is True
        assert result.score == 75

    async def test_parse_evaluator_heuristic_fallback(self) -> None:
        """When JSON fails, heuristic parser determines pass/fail."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = "This code passes all quality checks and looks great."
        result = runner._parse_evaluator_result(output)

        assert result.passed is True
        assert result.feedback == output

    async def test_parse_evaluator_heuristic_fail(self) -> None:
        """Heuristic detects 'fail' keyword."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = "This code fails the quality check due to missing tests."
        result = runner._parse_evaluator_result(output)

        assert result.passed is False


# ---------------------------------------------------------------------------
# Tests: Evaluator criteria (REQ-04.41, REQ-04.44)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluatorCriteria:
    """Each evaluator defines its own rubric/criteria."""

    async def test_evaluator_uses_block_criteria(self) -> None:
        """Evaluator input includes criteria from block system_prompt."""
        team = _make_loop_team()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        loop_def = team.loops[0]
        eval_input = runner._build_evaluator_input(loop_def, "some artifact")

        # The evaluator block's system_prompt should be in the input
        evaluator_def = registry.get_block("evaluator")
        assert evaluator_def is not None
        assert evaluator_def.system_prompt in eval_input


@pytest.mark.unit
class TestEvaluatorCriteriaConfig:
    """Evaluator criteria are part of block config."""

    async def test_evaluator_criteria_from_config(self) -> None:
        """Evaluator uses system_prompt as criteria source."""
        registry = BlockRegistry()
        # Register a custom evaluator with specific criteria
        custom_eval = BlockDef(
            name="quality_eval",
            role="evaluator",
            system_prompt="Check for: correctness, performance, readability",
            inputs=[PortDef(name="artifact", type_tag="any")],
            outputs=[PortDef(name="result", type_tag="review")],
        )
        registry.register_block(custom_eval)

        team = TeamDef(
            name="criteria-team",
            blocks={
                "orchestrator": "planner",
                "gen": "coder",
                "eval": "quality_eval",
            },
            connections=[],
            loops=[
                LoopDef(generator_block="gen", evaluator_block="eval"),
            ],
            entry_block="orchestrator",
        )
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        eval_input = runner._build_evaluator_input(team.loops[0], "code here")
        assert "correctness, performance, readability" in eval_input


# ---------------------------------------------------------------------------
# Tests: Loop behavior (REQ-04.42, REQ-04.43)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoopContinuesUntilPass:
    """Loop exit checks pass — continues until pass: true."""

    async def test_loop_continues_until_pass(self) -> None:
        """Loop runs generator/evaluator until evaluator passes."""
        team = _make_loop_team()
        registry = BlockRegistry()

        # Generator produces output, evaluator fails twice then passes
        responses = [
            # Entry block (orchestrator)
            LLMResponse(content="Plan: write code", tool_calls=None),
            # Loop iteration 1: generator
            LLMResponse(content="def hello(): pass", tool_calls=None),
            # Loop iteration 1: evaluator (fail)
            LLMResponse(
                content='{"pass": false, "score": 30, "feedback": "No docstring"}',
                tool_calls=None,
            ),
            # Loop iteration 2: generator (improved)
            LLMResponse(content='def hello():\n    """Greet."""\n    pass', tool_calls=None),
            # Loop iteration 2: evaluator (pass)
            LLMResponse(
                content='{"pass": true, "score": 90, "feedback": "Good"}',
                tool_calls=None,
            ),
        ]
        provider = _make_provider(*responses)
        runner = TeamRunner(team, registry, provider)
        result = await runner.run("Write a hello function")

        # Should return the passing generator output
        assert "hello" in result
        assert "Greet" in result


@pytest.mark.unit
class TestLoopMaxIterations:
    """Max iteration safety limit per loop (default 5)."""

    async def test_loop_stops_at_max_iterations(self) -> None:
        """Loop stops at max_iterations even without pass."""
        team = TeamDef(
            name="limited-loop",
            blocks={
                "orchestrator": "planner",
                "gen": "coder",
                "eval": "evaluator",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="gen",
                    target_port="spec",
                ),
            ],
            loops=[
                LoopDef(
                    generator_block="gen",
                    evaluator_block="eval",
                    max_iterations=3,
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()

        # All evaluations fail — loop must stop at 3
        responses = [
            # Orchestrator
            LLMResponse(content="Plan", tool_calls=None),
        ]
        # 3 iterations: gen + eval each time (all fail)
        for i in range(3):
            responses.append(LLMResponse(content=f"attempt {i + 1}", tool_calls=None))
            responses.append(
                LLMResponse(
                    content='{"pass": false, "score": 20, "feedback": "Still bad"}',
                    tool_calls=None,
                )
            )

        provider = _make_provider(*responses)
        runner = TeamRunner(team, registry, provider)
        result = await runner.run("Generate something")

        # Should have the last generator output
        assert "attempt 3" in result
        # Provider should have been called exactly 7 times:
        # 1 (orchestrator) + 3*2 (gen+eval per iteration)
        assert provider.generate.call_count == 7

    async def test_loop_default_max_iterations_is_five(self) -> None:
        """Default max_iterations for a loop is 5."""
        loop = LoopDef(generator_block="gen", evaluator_block="eval")
        assert loop.max_iterations == 5


# ---------------------------------------------------------------------------
# Tests: Retry behavior (REQ-04.50)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBlockRetries:
    """Block fails -> retry N times."""

    async def test_block_retries_on_failure(self) -> None:
        """Block is retried max_retries times before failing."""
        team = TeamDef(
            name="retry-team",
            blocks={"orchestrator": "planner", "worker": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = _registry_with_retries(max_retries=2)

        # Orchestrator succeeds, worker fails twice then succeeds
        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan", tool_calls=None),  # orchestrator
            RuntimeError("fail 1"),  # worker attempt 1
            RuntimeError("fail 2"),  # worker attempt 2
            LLMResponse(content="Success on retry", tool_calls=None),  # worker attempt 3
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)
        result = await runner.run("Do work")

        assert result == "Success on retry"
        assert runner.agent_statuses["worker"] == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# Tests: Escalation (REQ-04.51, REQ-04.52, REQ-04.53)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEscalationAfterRetries:
    """Still failing -> escalate to caller."""

    async def test_block_escalates_after_retries_exhausted(self) -> None:
        """Block raises EscalationError after all retries fail."""
        team = TeamDef(
            name="escalate-team",
            blocks={"orchestrator": "planner", "worker": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = _registry_with_retries(max_retries=1)

        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan", tool_calls=None),  # orchestrator
            RuntimeError("fail 1"),  # worker attempt 1
            RuntimeError("fail 2"),  # worker attempt 2 (max_retries=1 -> 2 attempts)
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)

        with pytest.raises(EscalationError, match="worker"):
            await runner.run("Do work")


@pytest.mark.unit
class TestCallerDecision:
    """Caller decides: retry, skip, substitute, or escalate further."""

    async def test_caller_can_skip_failed_block(self) -> None:
        """Caller decision 'skip' returns a skip marker instead of raising."""
        team = TeamDef(
            name="skip-team",
            blocks={"orchestrator": "planner", "optional": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="optional",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = _registry_with_retries(max_retries=0)

        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan", tool_calls=None),
            RuntimeError("block fails"),
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)
        runner.set_caller_decision("optional", "skip")
        result = await runner.run("Do work")

        assert "SKIPPED" in result
        assert runner.agent_statuses["optional"] == AgentStatus.FAILED


@pytest.mark.unit
class TestHumanEscalation:
    """Error reaches entry agent -> escalate to human."""

    async def test_error_escalates_to_human_as_last_resort(self) -> None:
        """When no caller decision set, failure raises EscalationError."""
        team = TeamDef(
            name="human-escalate-team",
            blocks={"orchestrator": "planner", "worker": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = _registry_with_retries(max_retries=0)

        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan", tool_calls=None),
            RuntimeError("catastrophic failure"),
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)
        # No caller decision set — defaults to escalate

        with pytest.raises(EscalationError, match="human intervention"):
            await runner.run("Critical task")


# ---------------------------------------------------------------------------
# Tests: Parallel branch failure isolation (REQ-04.54)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParallelBranchIsolation:
    """Partial failure in parallel branches — other branches continue."""

    async def test_parallel_branches_continue_on_partial_failure(self) -> None:
        """If one branch fails with 'skip', other branches still run."""
        team = _make_parallel_team()
        registry = BlockRegistry()

        # coder (branch_a) has max_retries=1, so 2 attempts total
        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan for both branches", tool_calls=None),
            RuntimeError("branch_a fails"),  # branch_a attempt 1
            RuntimeError("branch_a fails"),  # branch_a attempt 2 (retry)
            LLMResponse(content="Research complete", tool_calls=None),  # branch_b
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)
        runner.set_caller_decision("branch_a", "skip")

        await runner.run("Research and code")

        # branch_b should have completed successfully
        assert runner.agent_statuses["branch_b"] == AgentStatus.COMPLETED
        # branch_a should be failed but skipped
        assert runner.agent_statuses["branch_a"] == AgentStatus.FAILED


# ---------------------------------------------------------------------------
# Tests: Missing branches — topological sort with diamond graph (line 122->120)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTopologicalSortDiamondGraph:
    """Diamond-shaped graph exercises the in-degree > 0 branch in topo sort."""

    async def test_diamond_graph_orders_correctly(self) -> None:
        """A diamond graph (A->B, A->C, B->D, C->D) exercises in-degree decrement
        where the neighbor's in-degree does not immediately reach zero."""
        team = TeamDef(
            name="diamond-team",
            blocks={
                "orchestrator": "planner",
                "branch_b": "coder",
                "branch_c": "researcher",
                "merge_d": "reviewer",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="branch_b",
                    target_port="spec",
                ),
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="branch_c",
                    target_port="question",
                ),
                Connection(
                    source_block="branch_b",
                    source_port="changes",
                    target_block="merge_d",
                    target_port="changes",
                ),
                Connection(
                    source_block="branch_c",
                    source_port="report",
                    target_block="merge_d",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        # orchestrator must be first, merge_d must be last
        assert order[0] == "orchestrator"
        assert order[-1] == "merge_d"
        # branch_b and branch_c must come before merge_d
        assert order.index("branch_b") < order.index("merge_d")
        assert order.index("branch_c") < order.index("merge_d")


# ---------------------------------------------------------------------------
# Tests: Missing branches — entry block already first (lines 231-232)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEntryBlockAlreadyFirst:
    """When topo sort already puts entry_block first, no reordering needed."""

    async def test_entry_block_naturally_first_no_reorder(self) -> None:
        """Entry block with in-degree 0 is naturally first in topo sort."""
        # Simple chain: orchestrator -> worker (orchestrator has in-degree 0)
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        assert order[0] == "orchestrator"
        assert len(order) == 2

    async def test_entry_block_not_first_gets_reordered(self) -> None:
        """Entry block that isn't naturally first gets moved to front."""
        # Create a team where another root node might sort before entry
        team = TeamDef(
            name="reorder-team",
            blocks={
                "aaa_first_alpha": "researcher",
                "orchestrator": "planner",
                "worker": "coder",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)
        order = runner._execution_order()

        # Regardless of natural sort order, orchestrator must be first
        assert order[0] == "orchestrator"


# ---------------------------------------------------------------------------
# Tests: Missing branches — gather_input with no upstream output (line 243->239)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatherInputUpstreamEmpty:
    """When upstream block has no stored output, _gather_input skips it."""

    async def test_gather_input_falls_back_when_upstream_has_no_output(self) -> None:
        """If upstream block has not produced output, fallback is used."""
        team = TeamDef(
            name="noop-upstream",
            blocks={
                "orchestrator": "planner",
                "worker_a": "coder",
                "worker_b": "reviewer",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker_b",
                    target_port="changes",
                ),
                # worker_a also connects to worker_b but has no output yet
                Connection(
                    source_block="worker_a",
                    source_port="changes",
                    target_block="worker_b",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        # Only orchestrator has output; worker_a does not
        runner._outputs["orchestrator"] = "Plan output"

        result = runner._gather_input("worker_b", "fallback input")

        # Should include orchestrator output but not fail on missing worker_a
        assert "Plan output" in result


# ---------------------------------------------------------------------------
# Tests: Missing branches — block type not found (line 263)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBlockTypeNotFound:
    """Block type not in registry raises BlockError immediately."""

    async def test_run_block_raises_when_block_type_not_found(self) -> None:
        """_run_block raises BlockError if the block type is not in the registry."""
        team = TeamDef(
            name="missing-type-team",
            blocks={
                "orchestrator": "planner",
                "mystery": "nonexistent_block_type",
            },
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="mystery",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        with pytest.raises(BlockError, match="nonexistent_block_type"):
            await runner._run_block("mystery", "some input")


# ---------------------------------------------------------------------------
# Tests: Missing branches — unknown caller decision (line 307)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnknownCallerDecision:
    """Unknown caller decision falls through to default escalation."""

    async def test_unknown_decision_escalates(self) -> None:
        """A decision that is neither 'skip' nor 'escalate' triggers default escalation."""
        team = TeamDef(
            name="unknown-decision-team",
            blocks={"orchestrator": "planner", "worker": "coder"},
            connections=[
                Connection(
                    source_block="orchestrator",
                    source_port="plan",
                    target_block="worker",
                    target_port="spec",
                ),
            ],
            entry_block="orchestrator",
        )
        registry = _registry_with_retries(max_retries=0)

        provider = AsyncMock()
        call_count = [0]
        responses = [
            LLMResponse(content="Plan", tool_calls=None),
            RuntimeError("block fails"),
        ]

        async def mock_generate(messages, tools=None):
            idx = call_count[0]
            call_count[0] += 1
            resp = responses[idx]
            if isinstance(resp, Exception):
                raise resp
            return resp

        provider.generate = mock_generate
        runner = TeamRunner(team, registry, provider)
        # Set an unrecognized decision value
        runner.set_caller_decision("worker", "substitute")

        with pytest.raises(EscalationError, match="worker"):
            await runner.run("Do work")


# ---------------------------------------------------------------------------
# Tests: Missing branches — evaluator with no system_prompt (lines 343->346, 347->350)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildEvaluatorInputNoCriteria:
    """Evaluator with no system_prompt yields input without criteria section."""

    async def test_evaluator_input_without_criteria_when_no_system_prompt(self) -> None:
        """When evaluator block has empty system_prompt, no criteria section appended."""
        # Register a custom evaluator with no system_prompt
        registry = BlockRegistry()
        no_prompt_eval = BlockDef(
            name="bare_eval",
            role="evaluator",
            system_prompt="",
            inputs=[PortDef(name="artifact", type_tag="any")],
            outputs=[PortDef(name="result", type_tag="review")],
        )
        registry.register_block(no_prompt_eval)

        team = TeamDef(
            name="no-criteria-team",
            blocks={
                "orchestrator": "planner",
                "gen": "coder",
                "eval": "bare_eval",
            },
            connections=[],
            loops=[
                LoopDef(generator_block="gen", evaluator_block="eval"),
            ],
            entry_block="orchestrator",
        )
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        eval_input = runner._build_evaluator_input(team.loops[0], "some artifact text")

        assert "Artifact to evaluate:" in eval_input
        assert "some artifact text" in eval_input
        # No criteria section should be present
        assert "Evaluation criteria:" not in eval_input

    async def test_evaluator_input_without_criteria_when_block_not_found(self) -> None:
        """When evaluator block type is not in registry, no criteria section appended."""
        registry = BlockRegistry()
        team = TeamDef(
            name="missing-eval-team",
            blocks={
                "orchestrator": "planner",
                "gen": "coder",
                "eval": "unknown_evaluator_type",
            },
            connections=[],
            loops=[
                LoopDef(generator_block="gen", evaluator_block="eval"),
            ],
            entry_block="orchestrator",
        )
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        eval_input = runner._build_evaluator_input(team.loops[0], "artifact data")

        assert "Artifact to evaluate:" in eval_input
        assert "Evaluation criteria:" not in eval_input


# ---------------------------------------------------------------------------
# Tests: Missing branches — embedded JSON parse failure (lines 397-398)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseJsonPermissiveEmbeddedFailure:
    """Embedded JSON that is malformed returns None from _parse_json_permissive."""

    async def test_embedded_json_malformed_returns_none(self) -> None:
        """When text has braces but content is not valid JSON, returns None."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        # Text with braces but invalid JSON inside
        output = "Here is my result: {not valid json at all} done"
        result = runner._parse_json_permissive(output)

        assert result is None

    async def test_embedded_json_parse_falls_to_heuristic(self) -> None:
        """When embedded JSON fails, evaluator falls back to heuristic parsing."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        output = "Evaluation: {broken json here} overall the code passes review."
        result = runner._parse_evaluator_result(output)

        # Falls through to heuristic: "pass" present, "fail" absent -> passed
        assert result.passed is True
        assert result.feedback == output


# ---------------------------------------------------------------------------
# Tests: _invoke_agent uses real tools (REQ-04.9)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvokeAgentToolExecutors:
    """_invoke_agent passes real tool executors when block has tools."""

    async def test_invoke_agent_passes_tools_when_block_has_tools(self) -> None:
        """Blocks with tools get real tool executors, not empty dict."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider(
            LLMResponse(content="Plan", tool_calls=None),
            LLMResponse(content="Done", tool_calls=None),
        )
        runner = TeamRunner(team, registry, provider)

        # The coder block has tools defined
        coder_def = registry.get_block("coder")
        assert coder_def is not None
        assert len(coder_def.tools) > 0

        with patch("guild.orchestration.team_runner.AgentLoop") as mock_loop_cls:
            mock_loop = AsyncMock()
            mock_loop.run = AsyncMock(return_value="coded result")
            mock_loop_cls.return_value = mock_loop

            await runner._invoke_agent(coder_def, "implement feature")

        # Verify AgentLoop was created with non-empty tool_executors
        call_kwargs = mock_loop_cls.call_args[1]
        assert len(call_kwargs["tool_executors"]) > 0
        assert "file_read" in call_kwargs["tool_executors"]

    async def test_invoke_agent_empty_tools_when_block_has_no_tools(self) -> None:
        """Blocks without tools get an empty tool executor dict."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider(
            LLMResponse(content="Plan", tool_calls=None),
        )
        runner = TeamRunner(team, registry, provider)

        # The planner block has no tools
        planner_def = registry.get_block("planner")
        assert planner_def is not None
        assert len(planner_def.tools) == 0

        with patch("guild.orchestration.team_runner.AgentLoop") as mock_loop_cls:
            mock_loop = AsyncMock()
            mock_loop.run = AsyncMock(return_value="planned result")
            mock_loop_cls.return_value = mock_loop

            await runner._invoke_agent(planner_def, "plan feature")

        # Verify AgentLoop was created with empty tool_executors
        call_kwargs = mock_loop_cls.call_args[1]
        assert call_kwargs["tool_executors"] == {}

    async def test_invoke_agent_reviewer_gets_self_review(self) -> None:
        """Reviewer role blocks are invoked with self_review=True."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        reviewer_def = registry.get_block("reviewer")
        assert reviewer_def is not None
        assert reviewer_def.role == "reviewer"

        with patch("guild.orchestration.team_runner.AgentLoop") as mock_loop_cls:
            mock_loop = AsyncMock()
            mock_loop.run = AsyncMock(return_value="review complete")
            mock_loop_cls.return_value = mock_loop

            await runner._invoke_agent(reviewer_def, "review code")

        # Verify run was called with self_review=True
        mock_loop.run.assert_called_once()
        call_kwargs = mock_loop.run.call_args[1]
        assert call_kwargs["self_review"] is True

    async def test_invoke_agent_non_reviewer_no_self_review(self) -> None:
        """Non-reviewer role blocks are invoked with self_review=False."""
        team = _make_team_with_entry()
        registry = BlockRegistry()
        provider = _make_provider()
        runner = TeamRunner(team, registry, provider)

        coder_def = registry.get_block("coder")
        assert coder_def is not None
        assert coder_def.role != "reviewer"

        with patch("guild.orchestration.team_runner.AgentLoop") as mock_loop_cls:
            mock_loop = AsyncMock()
            mock_loop.run = AsyncMock(return_value="code done")
            mock_loop_cls.return_value = mock_loop

            await runner._invoke_agent(coder_def, "write code")

        # Verify run was called with self_review=False
        call_kwargs = mock_loop.run.call_args[1]
        assert call_kwargs["self_review"] is False
