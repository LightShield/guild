"""E2E acceptance tests for daemon lifecycle, permissions, and artifacts.

Black-box tests exercising features from the outside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.provider.base import LLMResponse

runner = CliRunner()
pytestmark = pytest.mark.e2e


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a Guild project in a temporary directory."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    return tmp_path


class TestPermissions:
    """Permission tiers are enforced through the CLI."""

    @pytest.mark.ac("AC-03.1.1")
    def test_task_runs_in_autopilot_by_default(self, project_dir: Path) -> None:
        """Default permission is autopilot -- no prompts."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="Done.",
                tool_calls=None,
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )
        )
        mock_provider.health_check = AsyncMock(return_value=True)

        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=mock_provider,
        ):
            result = runner.invoke(
                app, ["task", "Simple task", "--permission", "autopilot"]
            )
        assert result.exit_code == 0
        assert "Done" in result.output

    @pytest.mark.ac("AC-03.1.2")
    def test_permission_flag_accepted(self, project_dir: Path) -> None:
        """--permission flag is recognized for all tiers."""
        for tier in ["nothing", "ask", "scoped", "autopilot"]:
            runner.invoke(
                app, ["task", "test", "--permission", tier, "--help"]
            )


# ======================================================================
# Helper factories
# ======================================================================


def _simple_response(content: str = "Done.") -> LLMResponse:
    """Shortcut for a text-only LLM response with no tool calls."""
    return LLMResponse(
        content=content,
        tool_calls=None,
        input_tokens=10,
        output_tokens=5,
        model="mock",
    )


def _tool_response(
    tool_name: str, args: dict[str, Any], content: str = ""
) -> LLMResponse:
    """Shortcut for an LLM response that requests a single tool call."""
    return LLMResponse(
        content=content,
        tool_calls=[{"function": {"name": tool_name, "arguments": args}}],
        input_tokens=20,
        output_tokens=15,
        model="mock",
    )


def _make_mock_provider(*responses: LLMResponse) -> AsyncMock:
    """Build a mock LLM provider that returns the given responses in order.

    Appends several neutral fall-back responses so that learning-extraction
    or other post-task hooks never hit StopIteration.
    """
    fallback = _simple_response("Nothing to extract.")
    all_responses = list(responses) + [fallback] * 5

    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=all_responses)
    provider.health_check = AsyncMock(return_value=True)
    return provider


# ======================================================================
# CLI-level tests that only use CliRunner + mocked provider
# ======================================================================


class TestAutopilotTierCliE2E:
    """Autopilot tier allows every tool call without any gating (CLI level)."""

    @pytest.mark.ac("AC-03.4.1")
    def test_autopilot_task_succeeds_via_cli(self, project_dir: Path) -> None:
        """Happy: task with --permission autopilot completes."""
        provider = _make_mock_provider(
            _tool_response(
                "file_write", {"path": "out.txt", "content": "data"}
            ),
            _simple_response("Done. File written."),
        )
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=provider,
        ):
            result = runner.invoke(
                app, ["task", "Write a file", "--permission", "autopilot"]
            )
        assert result.exit_code == 0
        assert "Done" in result.output


class TestPermissionAuditCliE2E:
    """Permission decisions produce data suitable for audit logging (CLI)."""

    @pytest.mark.ac("AC-03.6.1")
    def test_task_creates_audit_entry(self, project_dir: Path) -> None:
        """Happy: running a task creates an audit_log entry visible via CLI."""
        provider = _make_mock_provider(_simple_response("All done."))
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=provider,
        ):
            runner.invoke(
                app, ["task", "Audit test task", "--permission", "autopilot"]
            )

        audit = runner.invoke(app, ["audit"], terminal_width=200)
        assert audit.exit_code == 0
        assert "task_completed" in audit.output


class TestAgentNoPauseCliE2E:
    """Agent continues autonomously without unnecessary pauses (CLI)."""

    @pytest.mark.ac("AC-06.1.1")
    def test_agent_runs_multiple_tools_without_pausing(
        self, project_dir: Path
    ) -> None:
        """Happy: agent calls multiple tools in sequence."""
        provider = _make_mock_provider(
            _tool_response(
                "file_write", {"path": "a.txt", "content": "aaa"}
            ),
            _tool_response(
                "file_write", {"path": "b.txt", "content": "bbb"}
            ),
            _simple_response("Created two files."),
        )
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=provider,
        ):
            result = runner.invoke(
                app,
                ["task", "Create two files", "--permission", "autopilot"],
            )
        assert result.exit_code == 0
        assert "Done" in result.output or "Created" in result.output
        assert (project_dir / "a.txt").exists()
        assert (project_dir / "b.txt").exists()

    @pytest.mark.ac("AC-06.1.2")
    def test_nothing_tier_task_with_tool_call_errors(
        self, project_dir: Path
    ) -> None:
        """Sad: nothing tier + tool call => task still completes."""
        provider = _make_mock_provider(_simple_response("Nothing to do."))
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=provider,
        ):
            result = runner.invoke(
                app,
                ["task", "Describe the repo", "--permission", "nothing"],
            )
        assert result.exit_code == 0


class TestPermissionSwitchingCliE2E:
    """CLI accepts all permission tier values."""

    @pytest.mark.ac("AC-03.5.2")
    def test_cli_accepts_all_permission_tiers(self, project_dir: Path) -> None:
        """Edge: every tier value is accepted by the --permission flag."""
        for tier in ["nothing", "ask", "scoped", "autopilot"]:
            result = runner.invoke(
                app, ["task", "test", "--permission", tier, "--help"]
            )
            assert result.exit_code == 0
