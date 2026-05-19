"""Team execution engine — runs block compositions in topological order.

Handles loops (generator/evaluator pairs), retries, error escalation,
and parallel branch failure isolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

from guild.agent.loop import AgentLoop
from guild.config.constants import (
    AGENT_ID_PREFIX_LEN,
    BLOCK_RETRY_DELAY_SECONDS,
    BLOCK_RETRY_MAX,
    DEFAULT_LOOP_MAX_ITERATIONS,
    HEURISTIC_FAIL_SCORE,
    HEURISTIC_PASS_SCORE,
    LOOP_ESCALATION_THRESHOLD,
    PROVIDER_CHAIN_MAX_DEPTH,
    SUB_AGENT_MAX_TURNS,
    TASK_DESC_PREVIEW_CHARS,
    TASK_RESULT_PREVIEW_CHARS,
)
from guild.task.spec import TaskStatus

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.blocks.definition import BlockDef, LoopDef, TeamDef
    from guild.blocks.registry import BlockRegistry
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = [
    "AgentStatus",
    "BlockError",
    "DECISION_ESCALATE",
    "DECISION_SKIP",
    "EscalationError",
    "EvaluatorResult",
    "TeamRunner",
    "TeamRunnerConfig",
]

logger = get_logger(__name__)

DECISION_SKIP = "skip"
DECISION_ESCALATE = "escalate"
_LOOP_ESCALATION_THRESHOLD = LOOP_ESCALATION_THRESHOLD

_EVAL_PASS_KEY = "pass"
_EVAL_PASSED_KEY = "passed"
_EVAL_SCORE_KEY = "score"
_EVAL_FEEDBACK_KEY = "feedback"


def _extract_embedded_json(text: str) -> str | None:
    """Extract an embedded JSON object from surrounding text.

    Finds the first '{' and last '}' and returns the substring,
    or None if no valid boundaries exist.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


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
        """Initialize BlockError."""
        self.block_name = block_name
        super().__init__(f"Block '{block_name}' failed: {message}")


class EscalationError(Exception):
    """Raised when an error must be escalated to a human (REQ-04.53)."""

    def __init__(self, message: str) -> None:
        """Initialize EscalationError."""
        super().__init__(message)


@dataclass
class EvaluatorResult:
    """Standard evaluator output (REQ-04.40)."""

    passed: bool
    score: int  # 0-100
    feedback: str
    details: dict[str, Any] = field(default_factory=dict)


def _topological_sort(nodes: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm for topological sort.

    Args:
        nodes: All node identifiers.
        edges: Directed edges as (source, target) pairs.

    Returns:
        Nodes in topological order.
    """
    graph: dict[str, list[str]] = {name: [] for name in nodes}
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)

    for source, target in edges:
        graph[source].append(target)
        in_degree[target] += 1

    queue: list[str] = [name for name, degree in in_degree.items() if degree == 0]

    result: list[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


def _format_loop_feedback(
    initial_input: str, iteration: int, gen_output: str, feedback: str
) -> str:
    """Build the input for the next generator iteration from evaluator feedback."""
    return (
        f"{initial_input}\n\n"
        f"Previous attempt (iteration {iteration + 1}):\n{gen_output}\n\n"
        f"Feedback: {feedback}"
    )


@dataclass
class TeamRunnerConfig:
    """Configuration for the team runner."""

    storage: Storage | None = None
    working_dir: str | None = None


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
        config: TeamRunnerConfig | None = None,
    ) -> None:
        """Initialize TeamRunner."""
        if config is None:
            config = TeamRunnerConfig()
        self._team = team
        self._registry = registry
        self._provider = provider
        self._storage = config.storage
        self._working_dir = config.working_dir
        self._outputs: dict[str, str] = {}
        self._agent_statuses: dict[str, AgentStatus] = {}
        self._caller_decisions: dict[str, str] = {}
        self._preserved_messages: dict[str, list[dict[str, Any]]] = {}

    @property
    def agent_statuses(self) -> dict[str, AgentStatus]:
        """Current lifecycle state of each agent (REQ-04.9)."""
        return dict(self._agent_statuses)

    @property
    def preserved_messages(self) -> dict[str, list[dict[str, Any]]]:
        """Message histories preserved for paused agents (REQ-04.9)."""
        return dict(self._preserved_messages)

    def pause_agent(self, block_name: str, messages: list[dict[str, Any]]) -> None:
        """Pause an agent, preserving its message history for resume (REQ-04.9).

        Args:
            block_name: The block instance name to pause.
            messages: The full message history to preserve.
        """
        self._agent_statuses[block_name] = AgentStatus.PAUSED
        self._preserved_messages[block_name] = list(messages)
        logger.debug("Agent '%s' paused with %d messages preserved", block_name, len(messages))

    def resume_agent(self, block_name: str) -> list[dict[str, Any]]:
        """Resume a paused agent, returning its preserved message history.

        Args:
            block_name: The block instance name to resume.

        Returns:
            The preserved message history.
        """
        self._agent_statuses[block_name] = AgentStatus.RUNNING
        messages = self._preserved_messages.pop(block_name, [])
        logger.debug("Agent '%s' resumed with %d messages", block_name, len(messages))
        return messages

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
        loop_edges = {(loop.evaluator_block, loop.generator_block) for loop in self._team.loops}

        edges = [
            (conn.source_block, conn.target_block)
            for conn in self._team.connections
            if (conn.source_block, conn.target_block) not in loop_edges
        ]

        order = _topological_sort(list(self._team.blocks.keys()), edges)

        if self._team.entry_block in order and order[0] != self._team.entry_block:
            order.remove(self._team.entry_block)
            order.insert(0, self._team.entry_block)

        return order

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
        # Fail-fast: validate preconditions before any state mutations.
        block_type = self._team.blocks[instance_name]
        block_def = self._registry.get_block(block_type)
        if block_def is None:
            raise BlockError(instance_name, f"Block type '{block_type}' not found")
        max_retries = block_def.max_retries

        self._agent_statuses[instance_name] = AgentStatus.SPAWNED

        last_error: str = ""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                self._agent_statuses[instance_name] = AgentStatus.RUNNING
                result = await self._invoke_agent(block_def, input_data)
                self._agent_statuses[instance_name] = AgentStatus.COMPLETED
                return result
            except (
                BlockError,
                OSError,
                RuntimeError,
                ConnectionError,
                TimeoutError,
                ValueError,
            ) as exc:
                last_exc = exc
                last_error = str(exc)
                logger.warning(
                    "Block '%s' attempt %d/%d failed: %s",
                    instance_name,
                    attempt + 1,
                    max_retries + 1,
                    last_error,
                )

        self._agent_statuses[instance_name] = AgentStatus.FAILED
        raise BlockError(instance_name, last_error) from last_exc

    async def _run_block_with_escalation(self, instance_name: str, input_data: str) -> str:
        """Run a block, handling failure escalation (REQ-04.51-04.53)."""
        try:
            return await self._run_block(instance_name, input_data)
        except BlockError as err:
            return self._apply_failure_policy(instance_name, err)

    def _apply_failure_policy(self, instance_name: str, err: BlockError) -> str:
        """Handle a failed block per caller decision (REQ-04.52)."""
        decision = self._caller_decisions.get(instance_name, DECISION_ESCALATE)

        # Fail-fast: validate decision before applying any policy.
        if decision not in (DECISION_SKIP, DECISION_ESCALATE):
            raise EscalationError(f"Block '{instance_name}' failed: {err}")

        if decision == DECISION_SKIP:
            logger.warning("Skipping failed block '%s' per caller decision", instance_name)
            return f"[SKIPPED: {instance_name}]"
        raise EscalationError(
            f"Block '{instance_name}' failed and requires human intervention: {err}"
        )

    async def _run_loop(self, loop: LoopDef, initial_input: str) -> str:
        """Run a generator-evaluator loop (REQ-04.42/04.43).

        Continues until evaluator passes or max_iterations reached.
        After ESCALATION_THRESHOLD consecutive failures, escalates the
        generator block to the next model in the escalation chain.
        """
        max_iter = loop.max_iterations or DEFAULT_LOOP_MAX_ITERATIONS
        current_input = initial_input

        for iteration in range(max_iter):
            if iteration == _LOOP_ESCALATION_THRESHOLD:
                self._escalate_block_model(loop.generator_block)

            gen_output = await self._run_block(loop.generator_block, current_input)

            eval_input = self._build_evaluator_input(loop, gen_output)
            eval_output = await self._run_block(loop.evaluator_block, eval_input)

            result = self._parse_evaluator_result(eval_output)
            if result.passed:
                self._outputs[loop.generator_block] = gen_output
                self._outputs[loop.evaluator_block] = eval_output
                return gen_output

            current_input = _format_loop_feedback(
                initial_input, iteration, gen_output, result.feedback
            )

        self._outputs[loop.generator_block] = gen_output
        return gen_output

    def _escalate_block_model(self, block_instance: str) -> None:
        """Upgrade a block to use the next model in the escalation chain."""
        try:
            block_type = self._team.blocks.get(block_instance, "")
            block_def = self._registry.get_block(block_type)
            if block_def is None:
                return

            chain = self._get_escalation_chain()
            if not chain:
                return

            current_model = block_def.model or ""
            for candidate in chain:
                if candidate != current_model:
                    logger.info(
                        "Escalating block '%s' from %s to %s after %d failures",
                        block_instance,
                        current_model or "(default)",
                        candidate,
                        _LOOP_ESCALATION_THRESHOLD,
                    )
                    block_def.model = candidate
                    return
        except (AttributeError, KeyError, ValueError, FileNotFoundError, OSError):
            logger.debug("Block escalation skipped (no config)", exc_info=True)

    def _get_escalation_chain(self) -> list[str]:
        """Get escalation chain models from config, or empty list."""
        try:
            from guild.config.models import GuildConfig

            config: Any = GuildConfig.load(file=".guild/config.toml", args=[])
            chain = getattr(config, "escalation_chain", "")
            return [m.strip() for m in chain.split(",") if m.strip()]
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            return []

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
        json_result = self._try_parse_json(output)
        if json_result is not None:
            return json_result

        return self._parse_heuristic(output)

    def _try_parse_json(self, output: str) -> EvaluatorResult | None:
        """Attempt to parse output as JSON evaluator result."""
        data = self._parse_json_permissive(output)
        if not isinstance(data, dict):
            return None

        passed = data.get(_EVAL_PASS_KEY, data.get(_EVAL_PASSED_KEY, None))
        if passed is None:
            status = str(data.get("status", "")).lower()
            passed = status in ("pass", "success", "ok", "passed")
        score = int(data.get(_EVAL_SCORE_KEY, 0))
        feedback = str(data.get(_EVAL_FEEDBACK_KEY, ""))
        excluded_keys = {_EVAL_PASS_KEY, _EVAL_PASSED_KEY, _EVAL_SCORE_KEY, _EVAL_FEEDBACK_KEY}
        details = {k: v for k, v in data.items() if k not in excluded_keys}

        return EvaluatorResult(
            passed=bool(passed),
            score=max(0, min(100, score)),
            feedback=feedback,
            details=details,
        )

    @staticmethod
    def _parse_json_permissive(text: str) -> Any:
        """Parse JSON from text, trying embedded JSON if direct parse fails."""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        embedded = _extract_embedded_json(text)
        if embedded is None:
            return None
        try:
            return json.loads(embedded)
        except (json.JSONDecodeError, TypeError):
            return None

    def _parse_heuristic(self, output: str) -> EvaluatorResult:
        """Fallback heuristic parsing for evaluator output."""
        lower = output.lower()
        passed = "pass" in lower and "fail" not in lower
        score = HEURISTIC_PASS_SCORE if passed else HEURISTIC_FAIL_SCORE
        return EvaluatorResult(passed=passed, score=score, feedback=output)

    async def _create_block_task(self, block_def: BlockDef, input_data: str) -> tuple[str, str]:
        """Create a task and register the agent in storage.

        Returns:
            Tuple of (task_id, agent_id).
        """
        import uuid

        task_id = str(uuid.uuid4())
        agent_id = f"{block_def.name}-{task_id[:AGENT_ID_PREFIX_LEN]}"

        if self._storage:
            desc = f"[{block_def.name}] {input_data[:TASK_DESC_PREVIEW_CHARS]}"
            await self._storage.create_task(task_id, desc)
            await self._storage.register_agent(agent_id, block_def.name)
            await self._storage.update_task(
                task_id, assigned_agent=agent_id, status=TaskStatus.RUNNING.value
            )
            await self._storage.log_audit(
                "task_created",
                agent_id=agent_id,
                details=f"block={block_def.name}",
            )

        return task_id, agent_id

    async def _build_block_prompt(self, block_def: BlockDef) -> str:
        """Construct the system prompt, injecting learnings if storage is available."""
        from guild.agent.learning import format_learnings_for_injection
        from guild.config.constants import MIN_INJECTION_CONFIDENCE

        system_prompt = block_def.system_prompt
        if self._storage:
            learnings = await self._storage.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
            injection = format_learnings_for_injection(learnings)
            if injection:
                system_prompt = f"{system_prompt}\n\n{injection}"

        return system_prompt

    async def _persist_block_result(
        self, block_def: BlockDef, loop: AgentLoop, task_id: str, agent_id: str, result: str
    ) -> None:
        """Persist messages and mark the task as completed in storage."""
        if not self._storage:
            return

        for msg in loop.messages:
            if msg.role and msg.content:
                await self._storage.append_message(agent_id, msg.role, msg.content)
        await self._storage.update_task(
            task_id, status=TaskStatus.COMPLETED.value, result=result[:TASK_RESULT_PREVIEW_CHARS]
        )
        await self._storage.log_audit(
            "task_completed",
            agent_id=agent_id,
            details=f"block={block_def.name}",
        )

    async def _invoke_agent(self, block_def: BlockDef, input_data: str) -> str:
        """Invoke an agent for a block, using full task infrastructure."""
        from guild.tools.registry import build_tool_executors

        tool_executors = build_tool_executors() if block_def.tools else {}

        task_id, agent_id = await self._create_block_task(block_def, input_data)
        system_prompt = await self._build_block_prompt(block_def)

        provider = self._get_provider_for_block(block_def)

        from guild.agent.loop import AgentLoopConfig

        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            config=AgentLoopConfig(working_dir=self._working_dir, max_turns=SUB_AGENT_MAX_TURNS),
        )
        result = await loop.run(
            system_prompt=system_prompt,
            user_input=input_data,
            self_review=block_def.role == "reviewer",
        )

        await self._persist_block_result(block_def, loop, task_id, agent_id, result)
        return result

    def _get_provider_for_block(self, block_def: BlockDef) -> LLMProvider:
        """Get the provider for a block, using per-block model override if set."""
        if not block_def.model:
            return self._provider

        from guild.cli.task_runner import create_provider_for_backend
        from guild.provider.retry import RetryConfig, RetryProvider

        base_url = self._resolve_base_url()
        raw = create_provider_for_backend("ollama", base_url, block_def.model)
        config = RetryConfig(
            max_retries=BLOCK_RETRY_MAX,
            initial_delay_seconds=BLOCK_RETRY_DELAY_SECONDS,
        )
        return RetryProvider(raw, config=config)

    def _resolve_base_url(self) -> str:
        """Walk the provider chain to find the actual base_url."""
        candidate: Any = self._provider
        for _ in range(PROVIDER_CHAIN_MAX_DEPTH):
            url = getattr(candidate, "base_url", None)
            if url:
                return str(url)
            inner = getattr(candidate, "_provider", None) or getattr(candidate, "_chain", None)
            if inner is None:
                break
            if hasattr(inner, "current"):
                url = getattr(inner.current, "base_url", None)
                if url:
                    return str(url)
            candidate = inner
        return "http://localhost:11434"
