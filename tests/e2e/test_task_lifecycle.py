"""E2E acceptance tests for task lifecycle.

Tests the full flow: create task -> agent runs -> results persisted -> visible in history.
Provider is mocked at the boundary (it's external I/O), but everything else is real.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.provider.base import LLMResponse

runner = CliRunner()
pytestmark = pytest.mark.e2e


def _mock_provider() -> AsyncMock:
    """Create a mock provider that writes a file then says done.

    First call: returns a file_write tool call.
    Second call: returns final text with no tool calls.
    Subsequent calls: returns a neutral completion (guards against
    extra generate() calls from learning extraction or other hooks).
    """
    fallback_response = LLMResponse(
        content="Nothing to extract.",
        tool_calls=None,
        input_tokens=10,
        output_tokens=10,
        model="mock",
    )

    provider = AsyncMock()
    provider.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {
                                "path": "output.txt",
                                "content": "hello from guild",
                            },
                        }
                    }
                ],
                input_tokens=50,
                output_tokens=30,
                model="mock",
            ),
            LLMResponse(
                content="Done. I created output.txt with the requested content.",
                tool_calls=None,
                input_tokens=40,
                output_tokens=20,
                model="mock",
            ),
            # Extra responses for learning extraction or any other hooks
            fallback_response,
            fallback_response,
            fallback_response,
        ]
    )
    provider.health_check = AsyncMock(return_value=True)
    return provider


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a guild project via the CLI and chdir into it."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, f"guild init failed: {result.output}"
    return tmp_path


class TestTaskExecution:
    """Full lifecycle tests for task creation, execution, and observable outcomes."""

    @pytest.mark.ac("AC-06.8.1")
    def test_task_creates_file_and_completes(self, project_dir: Path) -> None:
        """Full lifecycle: task -> agent uses tool -> file created -> history updated."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(app, ["task", "Create output.txt"])

        assert result.exit_code == 0, f"Task failed: {result.output}"
        assert "Done" in result.output
        # Observable outcome: file was created by the real file_write tool
        assert (project_dir / "output.txt").exists()
        assert (project_dir / "output.txt").read_text() == "hello from guild"

    @pytest.mark.ac("AC-06.8.2")
    def test_task_appears_in_history(self, project_dir: Path) -> None:
        """After task completes, it shows in guild history."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            runner.invoke(app, ["task", "Create output.txt"])

        history = runner.invoke(app, ["history"], terminal_width=200)
        assert history.exit_code == 0
        assert "Create output.txt" in history.output or "completed" in history.output

    @pytest.mark.ac("AC-06.8.1")
    def test_task_empty_description_errors(self, project_dir: Path) -> None:
        """Sad path: empty description raises an error."""
        result = runner.invoke(app, ["task", ""])
        assert result.exit_code != 0 or "error" in result.output.lower()


class TestTaskTimeout:
    """Verify the --timeout flag is accepted and propagated."""

    @pytest.mark.ac("AC-06.7.1")
    def test_task_with_timeout_flag(self, project_dir: Path) -> None:
        """Task accepts --timeout flag and completes successfully."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(app, ["task", "Quick task", "--timeout", "60"])
        assert result.exit_code == 0


class TestUsageTracking:
    """Verify token usage is persisted and visible after a task runs."""

    @pytest.mark.ac("AC-10.3.1")
    def test_tokens_tracked_after_task(self, project_dir: Path) -> None:
        """After a task runs, token usage is visible in guild usage."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            runner.invoke(app, ["task", "Do something"])

        usage = runner.invoke(app, ["usage"], terminal_width=200)
        assert usage.exit_code == 0
        # Should show the token summary table with non-zero values
        # The mock returns 50+40=90 input tokens and 30+20=50 output tokens
        assert "90" in usage.output
        assert "50" in usage.output


class TestLearnings:
    """Verify the learnings command works on a fresh project."""

    @pytest.mark.ac("AC-09.1.1")
    def test_learnings_empty_initially(self, project_dir: Path) -> None:
        """Learnings command returns success on a fresh project."""
        result = runner.invoke(app, ["learnings"])
        assert result.exit_code == 0


class TestDecisions:
    """Verify the decisions command works on a fresh project."""

    @pytest.mark.ac("AC-06.12.1")
    def test_decisions_empty_initially(self, project_dir: Path) -> None:
        """Decisions command returns success on a fresh project."""
        result = runner.invoke(app, ["decisions"])
        assert result.exit_code == 0
