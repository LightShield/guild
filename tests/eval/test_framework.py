"""Tests for evaluation and benchmark framework (REQ-16)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from guild.eval.framework import (
    SELF_DEV_BENCHMARKS,
    BenchmarkTask,
    EvalFramework,
    EvalMetrics,
    EvalResult,
)
from guild.storage import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected in-memory-like storage for testing."""
    store = Storage(tmp_path / "test.db")
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


@pytest.fixture
def sample_task() -> BenchmarkTask:
    """A simple benchmark task for testing."""
    return BenchmarkTask(
        name="test_task",
        description="Write 'hello' to /tmp/test_out.txt",
        verification=[{"type": "file_exists", "path": "/tmp/test_out.txt"}],
        category="general",
    )


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Mock LLM provider that completes immediately."""
    from guild.provider.base import LLMResponse

    provider = AsyncMock()
    provider.generate.return_value = LLMResponse(
        content="Task completed.",
        tool_calls=None,
        input_tokens=100,
        output_tokens=50,
        model="test-model",
    )
    return provider


def _make_result(
    task_name: str = "test_task",
    model: str = "test-model",
    completed: bool = True,
    duration: float = 5.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
    tool_calls: int = 3,
    turns: int = 2,
) -> EvalResult:
    """Helper to create an EvalResult for testing."""
    return EvalResult(
        task_name=task_name,
        model=model,
        config_hash="abc123",
        metrics=EvalMetrics(
            task_completed=completed,
            duration_seconds=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=tool_calls,
            turns=turns,
        ),
        timestamp="2026-05-09T00:00:00+00:00",
    )


# ------------------------------------------------------------------
# REQ-16.1: A/B Testing
# ------------------------------------------------------------------


@pytest.mark.unit
class TestABTesting:
    """A/B testing runs same task on two providers and compares."""

    async def test_ab_test_runs_same_task_on_two_providers(
        self, storage: Storage, sample_task: BenchmarkTask, mock_provider: AsyncMock
    ) -> None:
        """A/B test invokes both providers with the same task."""
        provider_a = mock_provider
        provider_b = AsyncMock()
        from guild.provider.base import LLMResponse

        provider_b.generate.return_value = LLMResponse(
            content="Done.",
            tool_calls=None,
            input_tokens=200,
            output_tokens=100,
            model="model-b",
        )

        framework = EvalFramework(storage)
        result_a, result_b = await framework.run_ab_test(
            sample_task, provider_a, provider_b, "config-a", "config-b"
        )

        # Both should have run on the same task
        assert result_a.task_name == sample_task.name
        assert result_b.task_name == sample_task.name

    async def test_ab_test_returns_both_results(
        self, storage: Storage, sample_task: BenchmarkTask, mock_provider: AsyncMock
    ) -> None:
        """A/B test returns a tuple of two EvalResult objects."""
        provider_a = mock_provider
        provider_b = mock_provider

        framework = EvalFramework(storage)
        result_a, result_b = await framework.run_ab_test(
            sample_task, provider_a, provider_b, "label-a", "label-b"
        )

        assert isinstance(result_a, EvalResult)
        assert isinstance(result_b, EvalResult)
        assert result_a.config_hash == "label-a"
        assert result_b.config_hash == "label-b"


# ------------------------------------------------------------------
# REQ-16.2: Benchmark Suite
# ------------------------------------------------------------------


@pytest.mark.unit
class TestBenchmarkSuite:
    """Benchmark suite runs all tasks and collects results."""

    async def test_benchmark_suite_runs_all_tasks(
        self, storage: Storage, mock_provider: AsyncMock
    ) -> None:
        """Suite runs every task in the list."""
        tasks = [
            BenchmarkTask(
                name=f"task_{i}",
                description=f"Do thing {i}",
                verification=[],
                category="general",
            )
            for i in range(3)
        ]

        framework = EvalFramework(storage)
        results = await framework.run_suite(tasks, mock_provider, "suite-run")

        assert len(results) == 3
        assert all(isinstance(r, EvalResult) for r in results)
        names = [r.task_name for r in results]
        assert names == ["task_0", "task_1", "task_2"]

    async def test_builtin_benchmarks_exist(self) -> None:
        """Built-in benchmark tasks are defined and non-empty."""
        assert len(SELF_DEV_BENCHMARKS) >= 4
        for task in SELF_DEV_BENCHMARKS:
            assert isinstance(task, BenchmarkTask)
            assert task.name
            assert task.description


# ------------------------------------------------------------------
# REQ-16.3: Regression Detection
# ------------------------------------------------------------------


@pytest.mark.unit
class TestRegressionDetection:
    """Detect when config changes degrade performance."""

    async def test_detect_regression_on_worse_metrics(self, storage: Storage) -> None:
        """Regression detected when current is worse than baseline."""
        framework = EvalFramework(storage)

        baseline = _make_result(completed=True, duration=5.0, input_tokens=100, tool_calls=3)
        current = _make_result(completed=False, duration=15.0, input_tokens=500, tool_calls=10)

        regressed, reason = framework.detect_regression(current, baseline)

        assert regressed is True
        assert reason  # Non-empty explanation

    async def test_no_regression_on_equal_or_better(self, storage: Storage) -> None:
        """No regression when current matches or improves on baseline."""
        framework = EvalFramework(storage)

        baseline = _make_result(completed=True, duration=10.0, input_tokens=200, tool_calls=5)
        current = _make_result(completed=True, duration=8.0, input_tokens=150, tool_calls=4)

        regressed, reason = framework.detect_regression(current, baseline)

        assert regressed is False


# ------------------------------------------------------------------
# REQ-16.4: Eval Metrics
# ------------------------------------------------------------------


@pytest.mark.unit
class TestEvalMetrics:
    """Metrics capture all fields from an eval run."""

    async def test_eval_metrics_captures_all_fields(self) -> None:
        """EvalMetrics stores completion, duration, tokens, tool calls, turns."""
        metrics = EvalMetrics(
            task_completed=True,
            duration_seconds=12.5,
            input_tokens=500,
            output_tokens=200,
            tool_calls=7,
            turns=4,
        )

        assert metrics.task_completed is True
        assert metrics.duration_seconds == 12.5
        assert metrics.input_tokens == 500
        assert metrics.output_tokens == 200
        assert metrics.tool_calls == 7
        assert metrics.turns == 4
        assert metrics.error is None

    async def test_eval_records_duration(
        self, storage: Storage, sample_task: BenchmarkTask, mock_provider: AsyncMock
    ) -> None:
        """Eval run records non-zero duration."""
        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, mock_provider, "dur-test")

        assert result.metrics.duration_seconds > 0


# ------------------------------------------------------------------
# REQ-16.5: Results Storage
# ------------------------------------------------------------------


@pytest.mark.unit
class TestResultsStorage:
    """Eval results are stored and retrievable."""

    async def test_store_result_persists(self, storage: Storage) -> None:
        """Stored results persist in the database."""
        framework = EvalFramework(storage)
        result = _make_result(task_name="persist_test")

        await framework.store_result(result)
        results = await framework.get_results(task_name="persist_test")

        assert len(results) >= 1
        assert results[0].task_name == "persist_test"

    async def test_get_results_returns_stored(self, storage: Storage) -> None:
        """get_results retrieves previously stored results."""
        framework = EvalFramework(storage)

        r1 = _make_result(task_name="task_a", model="model-x")
        r2 = _make_result(task_name="task_b", model="model-y")
        await framework.store_result(r1)
        await framework.store_result(r2)

        all_results = await framework.get_results()
        assert len(all_results) >= 2

        filtered = await framework.get_results(task_name="task_a")
        assert all(r.task_name == "task_a" for r in filtered)


# ------------------------------------------------------------------
# REQ-16.6: Progressive Confidence Building
# ------------------------------------------------------------------


@pytest.mark.unit
class TestProgressiveConfidence:
    """Suite supports easy-to-hard progressive difficulty."""

    async def test_progressive_suite_easy_to_hard(self) -> None:
        """SELF_DEV_BENCHMARKS are ordered from simple to complex."""
        # The first task should be simpler (fewer verification steps)
        # than the last task
        assert len(SELF_DEV_BENCHMARKS) >= 4
        first = SELF_DEV_BENCHMARKS[0]
        last = SELF_DEV_BENCHMARKS[-1]

        # Simple tasks have fewer verification steps than complex ones
        assert len(first.verification) <= len(last.verification)


# ------------------------------------------------------------------
# REQ-16.7: Self-Development Benchmark
# ------------------------------------------------------------------


@pytest.mark.unit
class TestSelfDevBenchmarks:
    """Self-development benchmarks for agent capability testing."""

    async def test_self_dev_benchmarks_defined(self) -> None:
        """All expected self-dev benchmark tasks are defined."""
        names = [t.name for t in SELF_DEV_BENCHMARKS]

        assert "create_file" in names
        assert "read_and_report" in names
        assert "modify_existing" in names
        assert "multi_step" in names


# ------------------------------------------------------------------
# REQ-16.1: A/B Comparison Scoring (compare_results / _determine_winner)
# ------------------------------------------------------------------


@pytest.mark.unit
class TestCompareResults:
    """Tests for compare_results and _determine_winner scoring logic."""

    async def test_a_wins_when_a_completes_and_b_does_not(self, storage: Storage) -> None:
        """A wins outright when it completes but B does not."""
        framework = EvalFramework(storage)

        result_a = _make_result(completed=True, duration=10.0, input_tokens=200)
        result_b = _make_result(completed=False, duration=5.0, input_tokens=100)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "a"
        assert comparison["a_completed"] is True
        assert comparison["b_completed"] is False

    async def test_b_wins_when_b_completes_and_a_does_not(self, storage: Storage) -> None:
        """B wins outright when it completes but A does not."""
        framework = EvalFramework(storage)

        result_a = _make_result(completed=False, duration=5.0, input_tokens=100)
        result_b = _make_result(completed=True, duration=10.0, input_tokens=200)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "b"
        assert comparison["a_completed"] is False
        assert comparison["b_completed"] is True

    async def test_a_wins_on_better_duration_and_tokens(self, storage: Storage) -> None:
        """A wins when it has better duration and fewer tokens."""
        framework = EvalFramework(storage)

        result_a = _make_result(completed=True, duration=5.0, input_tokens=100, output_tokens=50)
        result_b = _make_result(completed=True, duration=10.0, input_tokens=200, output_tokens=100)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "a"

    async def test_b_wins_on_better_duration_and_tokens(self, storage: Storage) -> None:
        """B wins when it has better duration and fewer tokens."""
        framework = EvalFramework(storage)

        result_a = _make_result(completed=True, duration=10.0, input_tokens=200, output_tokens=100)
        result_b = _make_result(completed=True, duration=5.0, input_tokens=100, output_tokens=50)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "b"

    async def test_tie_when_metrics_equal(self, storage: Storage) -> None:
        """Tie when both complete with identical duration and tokens."""
        framework = EvalFramework(storage)

        result_a = _make_result(completed=True, duration=5.0, input_tokens=100, output_tokens=50)
        result_b = _make_result(completed=True, duration=5.0, input_tokens=100, output_tokens=50)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "tie"

    async def test_tie_when_one_metric_each_wins(self, storage: Storage) -> None:
        """Tie when A wins on duration but B wins on tokens."""
        framework = EvalFramework(storage)

        # A has better duration, B has fewer tokens
        result_a = _make_result(completed=True, duration=3.0, input_tokens=300, output_tokens=200)
        result_b = _make_result(completed=True, duration=10.0, input_tokens=50, output_tokens=50)

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["winner"] == "tie"

    async def test_compare_results_includes_all_fields(self, storage: Storage) -> None:
        """compare_results dict includes all expected fields."""
        framework = EvalFramework(storage)

        result_a = _make_result(
            task_name="my_task",
            model="model-a",
            completed=True,
            duration=5.0,
            input_tokens=100,
            output_tokens=50,
            tool_calls=3,
        )
        result_b = _make_result(
            task_name="my_task",
            model="model-b",
            completed=True,
            duration=8.0,
            input_tokens=200,
            output_tokens=100,
            tool_calls=5,
        )

        comparison = framework.compare_results(result_a, result_b)

        assert comparison["task_name"] == "my_task"
        assert comparison["a_model"] == "model-a"
        assert comparison["b_model"] == "model-b"
        assert comparison["a_duration"] == 5.0
        assert comparison["b_duration"] == 8.0
        assert comparison["a_tokens"] == 150
        assert comparison["b_tokens"] == 300
        assert comparison["a_tool_calls"] == 3
        assert comparison["b_tool_calls"] == 5


# ------------------------------------------------------------------
# Eval turn loop exception handling (lines 138-143)
# ------------------------------------------------------------------


@pytest.mark.unit
class TestEvalTurnLoopExceptionHandling:
    """Exception during eval turn loop sets completed=False and records error."""

    async def test_connection_error_during_eval_marks_incomplete(
        self, storage: Storage, sample_task: BenchmarkTask
    ) -> None:
        """ConnectionError during provider.generate marks task as not completed."""
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=ConnectionError("server unreachable"))

        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, provider, "err-test")

        assert result.metrics.task_completed is False
        assert result.metrics.error is not None
        assert "server unreachable" in result.metrics.error

    async def test_timeout_error_during_eval_marks_incomplete(
        self, storage: Storage, sample_task: BenchmarkTask
    ) -> None:
        """TimeoutError during provider.generate marks task as not completed."""
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=TimeoutError("request timed out"))

        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, provider, "timeout-test")

        assert result.metrics.task_completed is False
        assert result.metrics.error is not None
        assert "request timed out" in result.metrics.error

    async def test_runtime_error_during_eval_marks_incomplete(
        self, storage: Storage, sample_task: BenchmarkTask
    ) -> None:
        """RuntimeError during provider.generate marks task as not completed."""
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=RuntimeError("internal failure"))

        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, provider, "runtime-test")

        assert result.metrics.task_completed is False
        assert "internal failure" in result.metrics.error

    async def test_value_error_during_eval_marks_incomplete(
        self, storage: Storage, sample_task: BenchmarkTask
    ) -> None:
        """ValueError during provider.generate marks task as not completed."""
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=ValueError("bad input"))

        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, provider, "value-test")

        assert result.metrics.task_completed is False
        assert "bad input" in result.metrics.error

    async def test_error_after_partial_turns_preserves_partial_metrics(
        self, storage: Storage, sample_task: BenchmarkTask
    ) -> None:
        """Error after partial turns preserves accumulated metrics."""
        from guild.provider.base import LLMResponse

        provider = AsyncMock()
        # First call succeeds with a tool call, second call raises
        provider.generate = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="working...",
                    tool_calls=[{"name": "file_read", "arguments": {"path": "x"}}],
                    input_tokens=50,
                    output_tokens=25,
                    model="test-model",
                ),
                ConnectionError("lost connection"),
            ]
        )

        framework = EvalFramework(storage)
        result = await framework.run_eval(sample_task, provider, "partial-test")

        assert result.metrics.task_completed is False
        assert result.metrics.turns == 2
        assert result.metrics.input_tokens == 50
        assert result.metrics.output_tokens == 25
        assert result.metrics.tool_calls == 1
        assert result.metrics.error is not None
