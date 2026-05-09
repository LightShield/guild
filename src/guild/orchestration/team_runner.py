"""Team execution engine — runs block compositions in topological order.

Handles loops (generator/evaluator pairs), retries, error escalation,
and parallel branch failure isolation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from guild.agent.loop import AgentLoop

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.blocks.definition import BlockDef, LoopDef, TeamDef
    from guild.blocks.registry import BlockRegistry
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = [
    "AgentStatus",
    "BlockError",
    "EscalationError",
    "EvaluatorResult",
    "TeamRunner",
]

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 1
_DEFAULT_LOOP_MAX_ITERATIONS = 5


class AgentStatus(Enum):
    """Lifecycle states for a running agent (REQ-04.9)."""

    SPAWNED = "spawned"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class BlockError(Exception):
    """Raised when a block fails after all retries are exhausted."""

    def __init__(self, block_name: str, message: str) -> None:
        self.block_name = block_name
        super().__init__(f"Block '{block_name}' failed: {message}")


class EscalationError(Exception):
    """Raised when an error must be escalated to a human (REQ-04.53)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass
class EvaluatorResult:
    """Standard evaluator output (REQ-04.40)."""

    passed: bool
    score: int  # 0-100
    feedback: str
    details: dict[str, Any] = field(default_factory=dict)


class TeamRunner:
    """Executes a team composition by running blocks in topological order.

    Responsibilities:
    - Determine execution order via topological sort (REQ-04.1/04.2)
    - Track agent lifecycle (REQ-04.9)
    - Run generator/evaluator loops (REQ-04.42/04.43)
    - Retry failed blocks (REQ-04.50)
    - Escalate unrecoverable failures (REQ-04.51-04.54)
    """

    def __init__(
        self,
        team: TeamDef,
        registry: BlockRegistry,
        provider: LLMProvider,
        storage: Storage | None = None,
        working_dir: str | None = None,
    ) -> None:
        self._team = team
        self._registry = registry
        self._provider = provider
        self._storage = storage
        self._working_dir = working_dir
        self._outputs: dict[str, str] = {}
        self._agent_statuses: dict[str, AgentStatus] = {}
        self._caller_decisions: dict[str, str] = {}

    @property
    def agent_statuses(self) -> dict[str, AgentStatus]:
        """Current lifecycle state of each agent (REQ-04.9)."""
        return dict(self._agent_statuses)

    def set_caller_decision(self, block_name: str, decision: str) -> None:
        """Pre-set a caller decision for handling block failure (REQ-04.52).

        Valid decisions: 'retry', 'skip', 'substitute', 'escalate'.
        """
        self._caller_decisions[block_name] = decision

    async def run(self, initial_input: str) -> str:
        """Run the team on an initial input. Returns final output.

        Steps:
        1. Determine execution order (topological sort)
        2. For each block: gather inputs, run agent, handle loops/failures
        """
        order = self._execution_order()
        self._outputs[self._team.entry_block] = initial_input
        loop_handled = self._loop_handled_blocks()

        last_output = initial_input
        for instance_name in order:
            # Skip blocks handled inside a loop (evaluators)
            if instance_name in loop_handled:
                continue

            input_data = self._gather_input(instance_name, initial_input)
            loop_def = self._find_loop_for_generator(instance_name)

            if loop_def:
                last_output = await self._run_loop(loop_def, input_data)
            else:
                last_output = await self._run_block_with_escalation(instance_name, input_data)
            self._outputs[instance_name] = last_output

        return last_output

    def _loop_handled_blocks(self) -> set[str]:
        """Return block names that are handled inside loops (evaluators)."""
        handled: set[str] = set()
        for loop in self._team.loops:
            handled.add(loop.evaluator_block)
        return handled

    def _execution_order(self) -> list[str]:
        """Topological sort of team blocks, breaking cycles at loop edges.

        Entry block is always first (REQ-04.1).
        """
        loop_edges = set()
        for loop in self._team.loops:
            loop_edges.add((loop.evaluator_block, loop.generator_block))

        # Build adjacency (non-loop edges only)
        graph: dict[str, list[str]] = {name: [] for name in self._team.blocks}
        in_degree: dict[str, int] = dict.fromkeys(self._team.blocks, 0)

        for conn in self._team.connections:
            edge = (conn.source_block, conn.target_block)
            if edge in loop_edges:
                continue
            graph[conn.source_block].append(conn.target_block)
            in_degree[conn.target_block] += 1

        # Kahn's algorithm with entry_block priority
        queue: list[str] = []
        for name, degree in in_degree.items():
            if degree == 0:
                queue.append(name)

        # Ensure entry_block is first
        if self._team.entry_block in queue:
            queue.remove(self._team.entry_block)
            queue.insert(0, self._team.entry_block)

        result: list[str] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If entry_block not at index 0, force it there
        if result and result[0] != self._team.entry_block:
            if self._team.entry_block in result:
                result.remove(self._team.entry_block)
            result.insert(0, self._team.entry_block)

        return result

    def _gather_input(self, instance_name: str, fallback: str) -> str:
        """Gather inputs from upstream block outputs for a given block."""
        parts: list[str] = []
        for conn in self._team.connections:
            if conn.target_block != instance_name:
                continue
            upstream_output = self._outputs.get(conn.source_block)
            if upstream_output:
                parts.append(upstream_output)

        return "\n\n".join(parts) if parts else fallback

    def _find_loop_for_generator(self, instance_name: str) -> LoopDef | None:
        """Find a loop definition where this block is the generator."""
        for loop in self._team.loops:
            if loop.generator_block == instance_name:
                return loop
        return None

    async def _run_block(self, instance_name: str, input_data: str) -> str:
        """Run a single block instance with retry logic (REQ-04.50).

        Raises BlockError if all retries are exhausted.
        """
        block_type = self._team.blocks[instance_name]
        block_def = self._registry.get_block(block_type)
        if block_def is None:
            raise BlockError(instance_name, f"Block type '{block_type}' not found")

        max_retries = block_def.max_retries
        self._agent_statuses[instance_name] = AgentStatus.SPAWNED

        last_error: str = ""
        for attempt in range(max_retries + 1):
            try:
                self._agent_statuses[instance_name] = AgentStatus.RUNNING
                result = await self._invoke_agent(block_def, input_data)
                self._agent_statuses[instance_name] = AgentStatus.COMPLETED
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Block '%s' attempt %d/%d failed: %s",
                    instance_name,
                    attempt + 1,
                    max_retries + 1,
                    last_error,
                )

        self._agent_statuses[instance_name] = AgentStatus.FAILED
        raise BlockError(instance_name, last_error)

    async def _run_block_with_escalation(self, instance_name: str, input_data: str) -> str:
        """Run a block, handling failure escalation (REQ-04.51-04.53)."""
        try:
            return await self._run_block(instance_name, input_data)
        except BlockError as err:
            return self._handle_block_failure(instance_name, err)

    def _handle_block_failure(self, instance_name: str, err: BlockError) -> str:
        """Handle a failed block per caller decision (REQ-04.52)."""
        decision = self._caller_decisions.get(instance_name, "escalate")

        if decision == "skip":
            logger.info("Skipping failed block '%s' per caller decision", instance_name)
            return f"[SKIPPED: {instance_name}]"
        if decision == "escalate":
            raise EscalationError(
                f"Block '{instance_name}' failed and requires human intervention: {err}"
            )
        # Default: escalate
        raise EscalationError(f"Block '{instance_name}' failed: {err}")

    async def _run_loop(self, loop: LoopDef, initial_input: str) -> str:
        """Run a generator-evaluator loop (REQ-04.42/04.43).

        Continues until evaluator passes or max_iterations reached.
        """
        max_iter = loop.max_iterations or _DEFAULT_LOOP_MAX_ITERATIONS
        current_input = initial_input

        for iteration in range(max_iter):
            # Run generator
            gen_output = await self._run_block(loop.generator_block, current_input)

            # Run evaluator with criteria from block config
            eval_input = self._build_evaluator_input(loop, gen_output)
            eval_output = await self._run_block(loop.evaluator_block, eval_input)

            result = self._parse_evaluator_result(eval_output)
            if result.passed:
                self._outputs[loop.generator_block] = gen_output
                self._outputs[loop.evaluator_block] = eval_output
                return gen_output

            # Feed feedback back for next iteration
            current_input = (
                f"{initial_input}\n\n"
                f"Previous attempt (iteration {iteration + 1}):\n{gen_output}\n\n"
                f"Feedback: {result.feedback}"
            )

        # Max iterations reached — return last generator output
        self._outputs[loop.generator_block] = gen_output  # type: ignore[possibly-undefined]
        return gen_output  # type: ignore[possibly-undefined]

    def _build_evaluator_input(self, loop: LoopDef, artifact: str) -> str:
        """Build evaluator input including criteria from config (REQ-04.44)."""
        evaluator_type = self._team.blocks.get(loop.evaluator_block, "")
        evaluator_def = self._registry.get_block(evaluator_type)

        criteria = ""
        if evaluator_def and evaluator_def.system_prompt:
            criteria = evaluator_def.system_prompt

        parts = [f"Artifact to evaluate:\n{artifact}"]
        if criteria:
            parts.append(f"Evaluation criteria:\n{criteria}")

        return "\n\n".join(parts)

    def _parse_evaluator_result(self, output: str) -> EvaluatorResult:
        """Parse evaluator text output into structured result (REQ-04.40).

        Tries JSON parsing first, then keyword heuristics.
        """
        # Try JSON parsing
        json_result = self._try_parse_json(output)
        if json_result is not None:
            return json_result

        # Keyword heuristics fallback
        return self._parse_heuristic(output)

    def _try_parse_json(self, output: str) -> EvaluatorResult | None:
        """Attempt to parse output as JSON evaluator result."""
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            # Try to find JSON embedded in text
            start = output.find("{")
            end = output.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            try:
                data = json.loads(output[start:end])
            except (json.JSONDecodeError, TypeError):
                return None

        if not isinstance(data, dict):
            return None

        # Normalize field names
        passed = data.get("pass", data.get("passed", False))
        score = int(data.get("score", 0))
        feedback = str(data.get("feedback", ""))
        excluded_keys = {"pass", "passed", "score", "feedback"}
        details = {k: v for k, v in data.items() if k not in excluded_keys}

        return EvaluatorResult(
            passed=bool(passed),
            score=max(0, min(100, score)),
            feedback=feedback,
            details=details,
        )

    def _parse_heuristic(self, output: str) -> EvaluatorResult:
        """Fallback heuristic parsing for evaluator output."""
        lower = output.lower()
        passed = "pass" in lower and "fail" not in lower
        score = 80 if passed else 30
        return EvaluatorResult(passed=passed, score=score, feedback=output)

    async def _invoke_agent(self, block_def: BlockDef, input_data: str) -> str:
        """Invoke an AgentLoop for a block definition."""
        loop = AgentLoop(
            provider=self._provider,
            tool_executors={},
            working_dir=self._working_dir,
            max_turns=30,
        )
        result = await loop.run(
            system_prompt=block_def.system_prompt,
            user_input=input_data,
        )
        return result
