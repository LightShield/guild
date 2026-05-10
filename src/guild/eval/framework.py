"""Evaluation and benchmark framework for Guild.

Provides A/B testing (REQ-16.1), benchmark suites (REQ-16.2),
regression detection (REQ-16.3), eval metrics (REQ-16.4),
persistent results (REQ-16.5), progressive confidence (REQ-16.6),
and self-development benchmarks (REQ-16.7).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from guild.agent.message import Message

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.provider.base import LLMProvider, LLMResponse
    from guild.storage import Storage

__all__ = [
    "BenchmarkTask",
    "EvalFramework",
    "EvalMetrics",
    "EvalResult",
    "SELF_DEV_BENCHMARKS",
]

logger = logging.getLogger(__name__)

# Regression thresholds
_DURATION_REGRESSION_FACTOR = 2.0  # 2x slower = regression
_TOKEN_REGRESSION_FACTOR = 2.0  # 2x more tokens = regression
_TOOL_CALL_REGRESSION_FACTOR = 2.0  # 2x more tool calls = regression
_EVAL_MAX_TURNS = 20


@dataclass
class EvalMetrics:
    """Metrics for a single eval run (REQ-16.4)."""

    task_completed: bool
    duration_seconds: float
    input_tokens: int
    output_tokens: int
    tool_calls: int
    turns: int
    error: str | None = None


@dataclass
class EvalResult:
    """Result of running an eval task."""

    task_name: str
    model: str
    config_hash: str
    metrics: EvalMetrics
    timestamp: str


@dataclass
class BenchmarkTask:
    """A standard task in the benchmark suite (REQ-16.2)."""

    name: str
    description: str
    verification: list[dict[str, Any]]
    category: str = "general"


class EvalFramework:
    """Evaluation and benchmarking system.

    Runs tasks against LLM providers, stores results, and detects
    regressions via comparison of metrics.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def run_eval(
        self, task: BenchmarkTask, provider: LLMProvider, config_label: str
    ) -> EvalResult:
        """Run a single eval task and return metrics."""
        start = time.monotonic()
        metrics, model_name = await self._run_eval_turns(task, provider, config_label)
        duration = time.monotonic() - start

        return EvalResult(
            task_name=task.name,
            model=model_name,
            config_hash=config_label,
            metrics=EvalMetrics(
                task_completed=metrics["completed"],
                duration_seconds=duration,
                input_tokens=metrics["total_input"],
                output_tokens=metrics["total_output"],
                tool_calls=metrics["total_tool_calls"],
                turns=metrics["turns"],
                error=metrics["error"],
            ),
            timestamp=datetime.now(UTC).isoformat(),
        )

    async def _run_eval_turns(
        self, task: BenchmarkTask, provider: LLMProvider, config_label: str
    ) -> tuple[dict[str, Any], str]:
        """Execute the eval turn loop and return (metrics_dict, model_name)."""
        total_input = 0
        total_output = 0
        total_tool_calls = 0
        turns = 0
        completed = True
        error: str | None = None
        model_name = ""

        messages: list[Message] = [
            Message(role="user", content=task.description),
        ]

        try:
            for _ in range(_EVAL_MAX_TURNS):  # pragma: no branch
                turns += 1
                raw_messages = [m.to_dict() for m in messages]
                response: LLMResponse = await provider.generate(raw_messages)
                total_input += response.input_tokens
                total_output += response.output_tokens
                model_name = response.model or config_label

                messages.append(Message(role="assistant", content=response.content or ""))

                if not response.has_tool_call:
                    break

                tool_calls = response.tool_calls or []
                total_tool_calls += len(tool_calls)

        except (ConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
            completed = False
            error = str(exc)

        metrics = {
            "completed": completed,
            "total_input": total_input,
            "total_output": total_output,
            "total_tool_calls": total_tool_calls,
            "turns": turns,
            "error": error,
        }
        return metrics, model_name

    async def run_ab_test(
        self,
        task: BenchmarkTask,
        provider_a: LLMProvider,
        provider_b: LLMProvider,
        label_a: str,
        label_b: str,
    ) -> tuple[EvalResult, EvalResult]:
        """Run A/B test: same task on two providers (REQ-16.1)."""
        result_a = await self.run_eval(task, provider_a, label_a)
        result_b = await self.run_eval(task, provider_b, label_b)
        return result_a, result_b

    async def run_suite(
        self,
        tasks: list[BenchmarkTask],
        provider: LLMProvider,
        config_label: str,
    ) -> list[EvalResult]:
        """Run all tasks in the benchmark suite (REQ-16.2)."""
        results: list[EvalResult] = []
        for task in tasks:
            result = await self.run_eval(task, provider, config_label)
            results.append(result)
        return results

    async def store_result(self, result: EvalResult) -> None:
        """Persist an eval result to SQLite (REQ-16.5)."""
        await self._storage.store_eval_result(
            {
                "task_name": result.task_name,
                "model": result.model,
                "config_hash": result.config_hash,
                "task_completed": int(result.metrics.task_completed),
                "duration_seconds": result.metrics.duration_seconds,
                "input_tokens": result.metrics.input_tokens,
                "output_tokens": result.metrics.output_tokens,
                "tool_calls": result.metrics.tool_calls,
                "turns": result.metrics.turns,
                "error": result.metrics.error,
                "timestamp": result.timestamp,
            }
        )

    async def get_results(self, task_name: str | None = None, limit: int = 50) -> list[EvalResult]:
        """Retrieve stored eval results (REQ-16.5)."""
        rows = await self._storage.list_eval_results(task_name=task_name, limit=limit)
        return [self._row_to_result(row) for row in rows]

    def detect_regression(self, current: EvalResult, baseline: EvalResult) -> tuple[bool, str]:
        """Compare current to baseline for regression (REQ-16.3).

        Returns (regressed, reason).
        """
        reasons: list[str] = []

        # Task failure is always a regression
        if baseline.metrics.task_completed and not current.metrics.task_completed:
            reasons.append("task no longer completes")

        if (
            baseline.metrics.duration_seconds > 0
            and current.metrics.duration_seconds
            > baseline.metrics.duration_seconds * _DURATION_REGRESSION_FACTOR
        ):
            reasons.append(
                f"duration {current.metrics.duration_seconds:.1f}s"
                f" vs baseline {baseline.metrics.duration_seconds:.1f}s"
            )

        baseline_tokens = baseline.metrics.input_tokens + baseline.metrics.output_tokens
        current_tokens = current.metrics.input_tokens + current.metrics.output_tokens
        if baseline_tokens > 0 and current_tokens > baseline_tokens * _TOKEN_REGRESSION_FACTOR:
            reasons.append(f"tokens {current_tokens} vs baseline {baseline_tokens}")

        if (
            baseline.metrics.tool_calls > 0
            and current.metrics.tool_calls
            > baseline.metrics.tool_calls * _TOOL_CALL_REGRESSION_FACTOR
        ):
            reasons.append(
                f"tool_calls {current.metrics.tool_calls}"
                f" vs baseline {baseline.metrics.tool_calls}"
            )

        if reasons:
            return True, "; ".join(reasons)
        return False, ""

    def compare_results(self, result_a: EvalResult, result_b: EvalResult) -> dict[str, Any]:
        """Compare two results for A/B testing (REQ-16.1)."""
        return {
            "task_name": result_a.task_name,
            "a_model": result_a.model,
            "b_model": result_b.model,
            "a_completed": result_a.metrics.task_completed,
            "b_completed": result_b.metrics.task_completed,
            "a_duration": result_a.metrics.duration_seconds,
            "b_duration": result_b.metrics.duration_seconds,
            "a_tokens": (result_a.metrics.input_tokens + result_a.metrics.output_tokens),
            "b_tokens": (result_b.metrics.input_tokens + result_b.metrics.output_tokens),
            "a_tool_calls": result_a.metrics.tool_calls,
            "b_tool_calls": result_b.metrics.tool_calls,
            "winner": self._determine_winner(result_a, result_b),
        }

    def _determine_winner(self, result_a: EvalResult, result_b: EvalResult) -> str:
        """Determine which result is better based on metrics."""
        score_a = 0
        score_b = 0

        # Completion is most important
        if result_a.metrics.task_completed and not result_b.metrics.task_completed:
            return "a"
        if result_b.metrics.task_completed and not result_a.metrics.task_completed:
            return "b"

        if result_a.metrics.duration_seconds < result_b.metrics.duration_seconds:
            score_a += 1
        elif result_b.metrics.duration_seconds < result_a.metrics.duration_seconds:
            score_b += 1

        tokens_a = result_a.metrics.input_tokens + result_a.metrics.output_tokens
        tokens_b = result_b.metrics.input_tokens + result_b.metrics.output_tokens
        if tokens_a < tokens_b:
            score_a += 1
        elif tokens_b < tokens_a:
            score_b += 1

        if score_a > score_b:
            return "a"
        if score_b > score_a:
            return "b"
        return "tie"

    @staticmethod
    def _row_to_result(row: Any) -> EvalResult:
        """Convert a database row dict to an EvalResult."""
        return EvalResult(
            task_name=row["task_name"],
            model=row["model"],
            config_hash=row["config_hash"],
            metrics=EvalMetrics(
                task_completed=bool(row["task_completed"]),
                duration_seconds=row["duration_seconds"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                tool_calls=row["tool_calls"],
                turns=row["turns"],
                error=row["error"],
            ),
            timestamp=row["timestamp"],
        )


# ------------------------------------------------------------------
# Built-in benchmark tasks (REQ-16.7, REQ-16.6)
# Ordered from simple to complex for progressive confidence building.
# ------------------------------------------------------------------

SELF_DEV_BENCHMARKS: list[BenchmarkTask] = [
    BenchmarkTask(
        name="create_file",
        description="Create a file called 'output.txt' with the content 'hello world'",
        verification=[
            {"type": "file_exists", "path": "output.txt"},
        ],
        category="general",
    ),
    BenchmarkTask(
        name="read_and_report",
        description="Read the file 'input.txt' and report its line count",
        verification=[
            {"type": "output_contains", "substring": "lines"},
        ],
        category="general",
    ),
    BenchmarkTask(
        name="modify_existing",
        description=(
            "Read 'config.txt', change the line containing 'debug=false'"
            " to 'debug=true', and write it back"
        ),
        verification=[
            {"type": "file_exists", "path": "config.txt"},
            {"type": "file_contains", "path": "config.txt", "content": "debug=true"},
        ],
        category="coding",
    ),
    BenchmarkTask(
        name="multi_step",
        description=(
            "Read 'data_a.txt' and 'data_b.txt', combine their contents"
            " with a separator line '---', and write to 'combined.txt'"
        ),
        verification=[
            {"type": "file_exists", "path": "combined.txt"},
            {"type": "file_contains", "path": "combined.txt", "content": "---"},
            {"type": "output_contains", "substring": "combined"},
        ],
        category="coding",
    ),
]
