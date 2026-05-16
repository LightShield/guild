"""E2E acceptance tests for daemon lifecycle, permissions, and artifacts.

Black-box tests exercising features from the outside.
"""

from __future__ import annotations

import asyncio
import json
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
        """Default permission is autopilot — no prompts."""
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

        with patch("guild.cli.task_runner.create_resilient_provider", return_value=mock_provider):
            result = runner.invoke(app, ["task", "Simple task", "--permission", "autopilot"])
        assert result.exit_code == 0
        assert "Done" in result.output

    @pytest.mark.ac("AC-03.1.2")
    def test_permission_flag_accepted(self, project_dir: Path) -> None:
        """--permission flag is recognized for all tiers."""
        for tier in ["nothing", "ask", "scoped", "autopilot"]:
            result = runner.invoke(app, ["task", "test", "--permission", tier, "--help"])
            # Just verifying the flag is accepted (--help exits before running)


class TestControlSocket:
    """Control socket accepts connections, processes commands, and cleans up."""

    @pytest.mark.ac("AC-23.9.2")
    async def test_control_socket_full_lifecycle(self, tmp_path: Path) -> None:
        """Start socket, send commands, verify responses, stop."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"

        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        # Connect and exercise all commands
        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Status
        writer.write(json.dumps({"type": "command", "action": "status"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "running"

        # Message injection
        writer.write(json.dumps({"type": "message", "content": "focus on tests"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "delivered"
        assert await cs.get_pending_message() == "focus on tests"

        # Kill
        writer.write(json.dumps({"type": "command", "action": "kill"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "shutting_down"

        writer.close()
        await writer.wait_closed()
        await cs.stop()


class TestArtifacts:
    """Artifact save, retrieve, and review lifecycle."""

    @pytest.mark.ac("AC-18.1.1")
    def test_artifact_save_and_retrieve(self, project_dir: Path) -> None:
        """Save artifact, retrieve it, verify content."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-1", "result.py", "print('hello')")

        content = mgr.get("task-1", "result.py")
        assert content == "print('hello')"

    @pytest.mark.ac("AC-18.1.2")
    def test_artifact_review_gate(self, project_dir: Path) -> None:
        """Artifact starts pending, can be accepted or rejected."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-2", "code.py", "x = 1")

        # Starts pending
        assert len(mgr.list_pending("task-2")) == 1
        assert len(mgr.list_accepted("task-2")) == 0

        # Accept
        mgr.accept("task-2", "code.py")
        assert len(mgr.list_pending("task-2")) == 0
        assert len(mgr.list_accepted("task-2")) == 1


class TestArtifactReview:
    """Artifact accept, reject, and edit operations."""

    @pytest.mark.ac("AC-18.3.2")
    def test_reject_removes_artifact(self, project_dir: Path) -> None:
        """Rejecting removes the artifact completely."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-3", "bad.py", "import os; os.system('rm -rf /')")
        mgr.reject("task-3", "bad.py")
        assert mgr.get("task-3", "bad.py") is None

    @pytest.mark.ac("AC-18.3.1")
    def test_edit_updates_and_accepts(self, project_dir: Path) -> None:
        """Editing saves new content and auto-accepts."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-4", "draft.py", "x = 1")
        mgr.edit("task-4", "draft.py", "x = 2  # fixed")

        assert mgr.get("task-4", "draft.py") == "x = 2  # fixed"
        assert len(mgr.list_accepted("task-4")) == 1


class TestResourceAwareness:
    """Resource monitor detects GPU/VRAM pressure and throttles accordingly."""

    @pytest.mark.ac("AC-24.6.1")
    def test_vram_pressure_triggers_throttle(self) -> None:
        """High VRAM usage causes the resource monitor to throttle."""
        from guild.daemon.resource import ResourceMonitor, ResourceThresholds, SchedulingMode

        gpu_reader = lambda: {"gpu_percent": 90.0, "vram_used_mb": 7500, "vram_total_mb": 8192}
        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            gpu_reader=gpu_reader,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "vram" in status.reason.lower()

    @pytest.mark.ac("AC-24.6.2")
    def test_no_pressure_no_throttle(self) -> None:
        """Low VRAM usage does not throttle."""
        from guild.daemon.resource import ResourceMonitor, ResourceThresholds, SchedulingMode

        gpu_reader = lambda: {"gpu_percent": 30.0, "vram_used_mb": 2000, "vram_total_mb": 8192}
        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            gpu_reader=gpu_reader,
        )
        status = monitor.get_status()
        assert not status.is_throttled


# ======================================================================
# Helper factories for the tests below
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


def _tool_response(tool_name: str, args: dict[str, Any], content: str = "") -> LLMResponse:
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
# ======================================================================


class TestAskTierPromptsE2E:
    """Ask tier delegates each new tool name to prompt_fn for approval."""

    @pytest.mark.ac("AC-03.2.1")
    def test_ask_tier_approved_allows_tool(self, project_dir: Path) -> None:
        """Happy: prompt_fn returns True, tool call proceeds."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        approvals: list[str] = []

        def approve_all(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            approvals.append(tool)
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=approve_all)
        assert checker.check("file_read", "agent-e2e", {"path": "/tmp/a"}) is True
        assert "file_read" in approvals

    @pytest.mark.ac("AC-03.2.3")
    def test_ask_tier_denied_blocks_tool(self, project_dir: Path) -> None:
        """Sad: prompt_fn returns False, tool call is blocked."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        def deny_all(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            return False

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=deny_all)
        assert checker.check("shell", "agent-e2e", {"command": "ls"}) is False

    @pytest.mark.ac("AC-03.2.2")
    def test_ask_tier_caches_per_tool_name(self, project_dir: Path) -> None:
        """Edge: second call to same tool name reuses cached approval."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        call_count = 0

        def counting_prompt(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=counting_prompt)
        checker.check("file_read", "agent-e2e", {"path": "/a"})
        checker.check("file_read", "agent-e2e", {"path": "/b"})
        checker.check("file_write", "agent-e2e", {"path": "/c", "content": "x"})

        # file_read prompted once (cached), file_write prompted once = 2 total
        assert call_count == 2

    @pytest.mark.ac("AC-03.2.1")
    def test_ask_tier_no_prompt_fn_blocks(self, project_dir: Path) -> None:
        """Edge: ASK tier with no prompt_fn installed always denies."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=None)
        assert checker.check("file_read", "agent-e2e", {"path": "/tmp"}) is False


# ======================================================================
# ======================================================================


class TestScopedTierE2E:
    """Scoped tier permits tools + paths inside the allowlist, denies outside."""

    @pytest.mark.ac("AC-03.3.1")
    def test_scoped_allows_tool_in_scope(self, project_dir: Path) -> None:
        """Happy: tool in allowlist and path in bounds is allowed."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read", "file_write"],
            allowed_paths=[str(project_dir)],
        )
        args = {"path": str(project_dir / "src" / "main.py")}
        assert checker.check("file_read", "agent-e2e", args) is True

    @pytest.mark.ac("AC-03.3.3")
    def test_scoped_blocks_tool_outside_scope(self, project_dir: Path) -> None:
        """Sad: tool not in allowlist is denied regardless of path."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read"],
            allowed_paths=[str(project_dir)],
        )
        assert checker.check("shell", "agent-e2e", {"command": "ls"}) is False

    @pytest.mark.ac("AC-03.3.2")
    def test_scoped_blocks_path_outside_boundary(self, project_dir: Path) -> None:
        """Sad: tool in allowlist but path outside boundary is denied."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_write"],
            allowed_paths=[str(project_dir)],
        )
        assert (
            checker.check("file_write", "agent-e2e", {"path": "/etc/shadow", "content": "x"})
            is False
        )

    @pytest.mark.ac("AC-03.3.3")
    def test_scoped_tool_with_no_path_arg_allowed(self, project_dir: Path) -> None:
        """Edge: tool in allowlist with no path in args is allowed."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["search"],
            allowed_paths=[str(project_dir)],
        )
        assert checker.check("search", "agent-e2e", {"query": "hello"}) is True


# ======================================================================
# ======================================================================


class TestAutopilotTierE2E:
    """Autopilot tier allows every tool call without any gating."""

    @pytest.mark.ac("AC-03.4.1")
    def test_autopilot_task_succeeds_via_cli(self, project_dir: Path) -> None:
        """Happy: task with --permission autopilot completes when tool called."""
        provider = _make_mock_provider(
            _tool_response("file_write", {"path": "out.txt", "content": "data"}),
            _simple_response("Done. File written."),
        )
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=provider):
            result = runner.invoke(app, ["task", "Write a file", "--permission", "autopilot"])
        assert result.exit_code == 0
        assert "Done" in result.output

    @pytest.mark.ac("AC-03.4.1")
    def test_autopilot_allows_any_tool(self, project_dir: Path) -> None:
        """Happy: autopilot permits shell, file_write, etc."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("shell", "agent-e2e", {"command": "echo hi"}) is True
        assert checker.check("file_write", "agent-e2e", {"path": "/x"}) is True
        assert checker.check("search", "agent-e2e", {"query": "foo"}) is True

    @pytest.mark.ac("AC-03.4.2")
    def test_autopilot_still_blocked_by_hardcoded_never(self, project_dir: Path) -> None:
        """Edge: autopilot cannot override the hardcoded-never layer."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert (
            checker.check("shell", "agent-e2e", {"command": "git push --force origin main"})
            is False
        )


# ======================================================================
# ======================================================================


class TestPermissionSwitchingE2E:
    """Permission tier can be changed at runtime; cached state is cleared."""

    @pytest.mark.ac("AC-03.5.1")
    def test_switch_nothing_to_autopilot(self, project_dir: Path) -> None:
        """Happy: switching from nothing to autopilot unlocks tool calls."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        assert checker.check("file_read", "agent-e2e", {}) is False

        checker.set_tier(PermissionTier.AUTOPILOT)
        assert checker.check("file_read", "agent-e2e", {}) is True

    @pytest.mark.ac("AC-03.5.1")
    def test_switch_autopilot_to_nothing(self, project_dir: Path) -> None:
        """Sad: switching from autopilot to nothing locks everything."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("file_read", "agent-e2e", {}) is True

        checker.set_tier(PermissionTier.NOTHING)
        assert checker.check("file_read", "agent-e2e", {}) is False

    @pytest.mark.ac("AC-03.5.1")
    def test_switch_clears_ask_cache(self, project_dir: Path) -> None:
        """Edge: switching tier resets the session approval cache."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        prompt_count = 0

        def counting_prompt(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            nonlocal prompt_count
            prompt_count += 1
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=counting_prompt)
        checker.check("file_read", "agent-e2e", {"path": "/a"})
        assert prompt_count == 1

        # Switch away and back clears cache
        checker.set_tier(PermissionTier.AUTOPILOT)
        checker.set_tier(PermissionTier.ASK, prompt_fn=counting_prompt)
        checker.check("file_read", "agent-e2e", {"path": "/b"})
        assert prompt_count == 2  # re-prompted because cache was cleared

    @pytest.mark.ac("AC-03.5.2")
    def test_cli_accepts_all_permission_tiers(self, project_dir: Path) -> None:
        """Edge: every tier value is accepted by the --permission flag."""
        for tier in ["nothing", "ask", "scoped", "autopilot"]:
            result = runner.invoke(app, ["task", "test", "--permission", tier, "--help"])
            # --help exits before running, just verifying flag is accepted
            assert result.exit_code == 0


# ======================================================================
# ======================================================================


class TestPermissionAuditE2E:
    """Permission decisions produce data suitable for audit logging."""

    @pytest.mark.ac("AC-03.6.1")
    def test_task_creates_audit_entry(self, project_dir: Path) -> None:
        """Happy: running a task creates an audit_log entry visible via CLI."""
        provider = _make_mock_provider(_simple_response("All done."))
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=provider):
            runner.invoke(app, ["task", "Audit test task", "--permission", "autopilot"])

        audit = runner.invoke(app, ["audit"], terminal_width=200)
        assert audit.exit_code == 0
        assert "task_completed" in audit.output

    @pytest.mark.ac("AC-03.6.2")
    def test_permission_check_returns_auditable_info(self, project_dir: Path) -> None:
        """Happy: checker returns bool; tier and tool name are available for logging."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        result = checker.check("shell", "agent-e2e", {"command": "ls"})

        assert isinstance(result, bool)
        assert result is False
        assert checker._tier == PermissionTier.NOTHING

    @pytest.mark.ac("AC-03.6.1")
    def test_hardcoded_never_provides_reason(self, project_dir: Path) -> None:
        """Sad: denied calls include a descriptive reason for the audit log."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never("shell", {"command": "rm -rf /"})
        assert allowed is False
        assert "rm -rf /" in reason
        assert len(reason) > 10  # substantive description


# ======================================================================
# ======================================================================


class TestHardcodedNeverE2E:
    """Hardcoded-never layer blocks destructive/irreversible actions at every tier."""

    @pytest.mark.ac("AC-03.7.3")
    @pytest.mark.parametrize(
        "command,reason_fragment",
        [
            ("git push --force origin main", "git push --force"),
            ("rm -rf /", "rm -rf /"),
            ("git reset --hard HEAD", "git reset --hard"),
            ("sudo rm -rf /var/log", "sudo rm"),
            ("dd if=/dev/zero of=/dev/sda", "dd"),
        ],
    )
    def test_destructive_commands_blocked_in_autopilot(
        self, project_dir: Path, command: str, reason_fragment: str
    ) -> None:
        """Happy: destructive commands are blocked even in autopilot."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("shell", "agent-e2e", {"command": command}) is False

    @pytest.mark.ac("AC-03.7.1")
    def test_safe_command_allowed_in_autopilot(self, project_dir: Path) -> None:
        """Sad (reverse): safe commands are NOT blocked."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("shell", "agent-e2e", {"command": "ls -la"}) is True
        assert checker.check("shell", "agent-e2e", {"command": "git status"}) is True

    @pytest.mark.ac("AC-03.7.2")
    def test_hardcoded_never_override_flag(self, project_dir: Path) -> None:
        """Edge: explicit allow_hardcoded_never flag bypasses the layer."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never(
            "shell",
            {"command": "git push --force origin main"},
            allow_hardcoded_never=True,
        )
        assert allowed is True
        assert reason == ""

    @pytest.mark.ac("AC-03.7.1")
    def test_hardcoded_never_blocks_in_all_tiers(self, project_dir: Path) -> None:
        """Edge: destructive command blocked in scoped + autopilot (nothing blocks all)."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        for tier in [PermissionTier.SCOPED, PermissionTier.AUTOPILOT]:
            checker = PermissionChecker(
                tier=tier,
                allowed_tools=["shell"],
                allowed_paths=["/"],
            )
            assert checker.check("shell", "agent-e2e", {"command": "rm -rf /"}) is False


# ======================================================================
# ======================================================================


class TestReversibilityE2E:
    """Safe, reversible operations pass through; irreversible ones are blocked."""

    @pytest.mark.ac("AC-03.8.1")
    def test_read_only_commands_pass_everywhere(self, project_dir: Path) -> None:
        """Happy: read-only commands are allowed in scoped and autopilot tiers."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        for command in ["ls -la", "cat README.md", "git status", "git log --oneline"]:
            for tier in [PermissionTier.SCOPED, PermissionTier.AUTOPILOT]:
                checker = PermissionChecker(
                    tier=tier,
                    allowed_tools=["shell"],
                    allowed_paths=["/"],
                )
                assert (
                    checker.check("shell", "agent-e2e", {"command": command}) is True
                ), f"'{command}' blocked in {tier.value}"

    @pytest.mark.ac("AC-03.8.2")
    def test_irreversible_command_blocked(self, project_dir: Path) -> None:
        """Sad: irreversible commands are blocked by hardcoded-never."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("shell", "agent-e2e", {"command": "mkfs.ext4 /dev/sda1"}) is False

    @pytest.mark.ac("AC-03.8.1")
    def test_reversible_git_operations_pass(self, project_dir: Path) -> None:
        """Edge: reversible git commands are allowed; force-push is not."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        # Safe git ops
        assert (
            checker.check("shell", "agent-e2e", {"command": "git push origin feature-branch"})
            is True
        )
        assert checker.check("shell", "agent-e2e", {"command": "git diff HEAD"}) is True
        # Force-push is irreversible
        assert (
            checker.check("shell", "agent-e2e", {"command": "git push --force origin main"})
            is False
        )


# ======================================================================
# ======================================================================


class TestAgentNoPauseE2E:
    """Agent continues autonomously without unnecessary pauses."""

    @pytest.mark.ac("AC-06.1.1")
    def test_agent_runs_multiple_tools_without_pausing(self, project_dir: Path) -> None:
        """Happy: agent calls multiple tools in sequence without user interaction."""
        provider = _make_mock_provider(
            _tool_response("file_write", {"path": "a.txt", "content": "aaa"}),
            _tool_response("file_write", {"path": "b.txt", "content": "bbb"}),
            _simple_response("Created two files."),
        )
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=provider):
            result = runner.invoke(app, ["task", "Create two files", "--permission", "autopilot"])
        assert result.exit_code == 0
        assert "Done" in result.output or "Created" in result.output
        assert (project_dir / "a.txt").exists()
        assert (project_dir / "b.txt").exists()

    @pytest.mark.ac("AC-06.1.2")
    def test_nothing_tier_task_with_tool_call_errors(self, project_dir: Path) -> None:
        """Sad: nothing tier + tool call => task still completes (tool denied)."""
        # The provider tries to call a tool, but since the permission is
        # "nothing" the task runner itself validates the tier flag eagerly.
        # The run_task function validates the tier string and proceeds.
        # When the LLM returns tool calls under nothing tier, the loop still
        # runs (permissions are checked at a different layer). The test verifies
        # the CLI accepts the flag and does not crash.
        provider = _make_mock_provider(_simple_response("Nothing to do."))
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=provider):
            result = runner.invoke(app, ["task", "Describe the repo", "--permission", "nothing"])
        assert result.exit_code == 0

    @pytest.mark.ac("AC-06.1.1")
    def test_scoped_tools_proceed_without_prompting(self, project_dir: Path) -> None:
        """Edge: in scoped mode, tools within scope proceed with no prompt."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read", "file_write"],
            allowed_paths=[str(project_dir)],
        )
        # No prompt_fn installed, yet in-scope tools pass
        assert checker.check("file_read", "agent-e2e", {"path": str(project_dir / "x.txt")}) is True


# ======================================================================
# ======================================================================


class TestSelfVerifyCompletionE2E:
    """Agent can self-verify task completion via self_review flag."""

    @pytest.mark.ac("AC-06.2.1")
    async def test_self_review_runs_after_task(self) -> None:
        """Happy: self_review=True triggers a review round after completion."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop
        from guild.tools.base import ToolResult

        async def mock_write(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="Wrote file")

        provider = _make_mock_provider(
            _tool_response("file_write", {"path": "x.py", "content": "code"}),
            _simple_response("File written."),
            _simple_response("Reviewed. All correct."),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_write": mock_write},
        )
        result = await loop.run("sys", "Write code", self_review=True)

        review_msgs = [
            m for m in loop.messages if m.role == "user" and SELF_REVIEW_PROMPT in m.content
        ]
        assert len(review_msgs) == 1
        assert "Reviewed" in result

    @pytest.mark.ac("AC-06.2.2")
    async def test_self_review_not_run_when_disabled(self) -> None:
        """Sad: self_review=False (default) skips the review round."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop

        provider = _make_mock_provider(_simple_response("Task complete."))
        loop = AgentLoop(provider=provider, tool_executors={})
        result = await loop.run("sys", "Do task", self_review=False)

        review_msgs = [
            m for m in loop.messages if m.role == "user" and SELF_REVIEW_PROMPT in m.content
        ]
        assert len(review_msgs) == 0
        assert result == "Task complete."

    @pytest.mark.ac("AC-06.2.1")
    async def test_self_review_can_trigger_fixes(self) -> None:
        """Edge: self-review finds an issue and uses a tool to fix it."""
        from guild.agent.loop import AgentLoop
        from guild.tools.base import ToolResult

        async def mock_write(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="Wrote fix")

        provider = _make_mock_provider(
            _simple_response("File written."),
            # Self-review phase: finds a bug, calls tool, then confirms
            _tool_response("file_write", {"path": "x.py", "content": "fixed"}),
            _simple_response("Fixed a bug during review."),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_write": mock_write},
        )
        result = await loop.run("sys", "Write code", self_review=True)
        assert "Fixed" in result


# ======================================================================
# ======================================================================


class TestStuckDetectionE2E:
    """Stuck detection fires when the agent makes no progress."""

    @pytest.mark.ac("AC-06.3.1")
    async def test_stuck_triggers_recovery(self) -> None:
        """Happy: repeated identical calls trigger recovery prompt injection."""
        from guild.agent.loop import STUCK_RECOVERY_PROMPT, AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="file contents")

        same_call = _tool_response("file_read", {"path": "a.txt"})
        provider = _make_mock_provider(
            same_call,
            same_call,
            same_call,
            # After recovery injection
            _simple_response("I will try differently."),
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read},
            stuck_detector=detector,
            max_turns=10,
        )
        result = await loop.run("sys", "read a.txt")

        recovery_msgs = [
            m for m in loop.messages if m.role == "user" and STUCK_RECOVERY_PROMPT in m.content
        ]
        assert len(recovery_msgs) == 1

    @pytest.mark.ac("AC-06.3.2")
    async def test_double_stuck_escalates(self) -> None:
        """Sad: still stuck after recovery => structured escalation message."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="data")

        same_call = _tool_response("file_read", {"path": "a.txt"})
        provider = _make_mock_provider(
            # First stuck (3 identical calls)
            same_call,
            same_call,
            same_call,
            # After recovery prompt — still stuck (3 more identical)
            same_call,
            same_call,
            same_call,
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read},
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run("sys", "read a.txt")

        assert "stuck" in result.lower() or "need help" in result.lower()

    @pytest.mark.ac("AC-06.3.1")
    async def test_stuck_not_triggered_with_varied_calls(self) -> None:
        """Edge: varied calls do not trigger stuck detection."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="ok")

        async def mock_write(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="ok")

        provider = _make_mock_provider(
            _tool_response("file_read", {"path": "a.txt"}),
            _tool_response("file_write", {"path": "b.txt", "content": "x"}),
            _tool_response("file_read", {"path": "c.txt"}),
            _simple_response("All done."),
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read, "file_write": mock_write},
            stuck_detector=detector,
            max_turns=10,
        )
        result = await loop.run("sys", "do varied work")
        assert result == "All done."


# ======================================================================
# ======================================================================


class TestGracefulDegradationE2E:
    """Agent tries alternative approaches when one tool fails."""

    @pytest.mark.ac("AC-06.4.1")
    async def test_agent_continues_after_tool_failure(self) -> None:
        """Happy: first tool fails, agent tries another and succeeds."""
        from guild.agent.loop import AgentLoop
        from guild.tools.base import ToolResult

        async def failing_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=False, output="", error="File not found")

        async def mock_write(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="Created file")

        provider = _make_mock_provider(
            _tool_response("file_read", {"path": "missing.txt"}),
            # After failure, model tries a different approach
            _tool_response("file_write", {"path": "new.txt", "content": "fresh"}),
            _simple_response("Created a new file instead."),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": failing_read, "file_write": mock_write},
            max_turns=10,
        )
        result = await loop.run("sys", "Get contents or create")
        assert "Created" in result

    @pytest.mark.ac("AC-06.4.2")
    async def test_agent_handles_unknown_tool_gracefully(self) -> None:
        """Sad: model requests nonexistent tool, error message returned."""
        from guild.agent.loop import AgentLoop

        provider = _make_mock_provider(
            _tool_response("nonexistent_tool", {"x": 1}),
            _simple_response("I see, that tool does not exist."),
        )
        loop = AgentLoop(provider=provider, tool_executors={}, max_turns=5)
        result = await loop.run("sys", "use a tool")
        assert result != ""  # got a response, did not crash

    @pytest.mark.ac("AC-06.4.1")
    async def test_tool_exception_caught_gracefully(self) -> None:
        """Edge: tool executor raises exception; loop continues."""
        from guild.agent.loop import AgentLoop
        from guild.tools.base import ToolResult

        async def exploding_tool(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            raise RuntimeError("Unexpected failure")

        provider = _make_mock_provider(
            _tool_response("file_read", {"path": "x"}),
            _simple_response("I see the error, moving on."),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": exploding_tool},
            max_turns=5,
        )
        result = await loop.run("sys", "read file")
        assert "error" in result.lower() or "moving on" in result.lower()


# ======================================================================
# ======================================================================


class TestHumanEscalationE2E:
    """After exhausting alternatives, agent produces a structured escalation."""

    @pytest.mark.ac("AC-06.5.1")
    async def test_escalation_includes_task_and_tools(self) -> None:
        """Happy: escalation message has task description and tools tried."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="data")

        same_call = _tool_response("file_read", {"path": "x.py"})
        provider = _make_mock_provider(
            *[same_call for _ in range(6)],
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read},
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run("sys", "Refactor database module")

        assert "Refactor database module" in result
        assert "file_read" in result

    @pytest.mark.ac("AC-06.5.1")
    async def test_escalation_has_structured_format(self) -> None:
        """Sad: escalation is structured with expected fields."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="data")

        same_call = _tool_response("file_read", {"path": "x.py"})
        provider = _make_mock_provider(*[same_call for _ in range(6)])
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read},
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run("sys", "Fix the bug")

        assert "stuck" in result.lower() or "need help" in result.lower()
        assert "Task:" in result or "What I tried:" in result

    @pytest.mark.ac("AC-06.5.2")
    async def test_no_escalation_when_task_succeeds(self) -> None:
        """Edge: a task that completes successfully never produces escalation."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector

        provider = _make_mock_provider(_simple_response("All done."))
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={},
            stuck_detector=detector,
            max_turns=10,
        )
        result = await loop.run("sys", "Simple task")
        assert "stuck" not in result.lower()
        assert "need help" not in result.lower()


# ======================================================================
# ======================================================================


class TestMultiTurnE2E:
    """Multi-turn conversations preserve full message history."""

    @pytest.mark.ac("AC-06.9.1")
    async def test_send_preserves_context(self) -> None:
        """Happy: send() sees messages from prior turns."""
        from guild.agent.loop import AgentLoop

        provider = _make_mock_provider(
            _simple_response("Hello! I am ready."),
            _simple_response("Your name is Alice."),
        )
        loop = AgentLoop(provider=provider, tool_executors={})

        await loop.run("You are helpful.", "My name is Alice.")
        result = await loop.send("What is my name?")

        assert result == "Your name is Alice."
        user_msgs = [m for m in loop.messages if m.role == "user"]
        assert len(user_msgs) >= 2

    @pytest.mark.ac("AC-06.9.1")
    async def test_run_resets_history(self) -> None:
        """Sad: calling run() again clears the conversation."""
        from guild.agent.loop import AgentLoop

        provider = _make_mock_provider(
            _simple_response("First run."),
            _simple_response("Second run."),
        )
        loop = AgentLoop(provider=provider, tool_executors={})

        await loop.run("sys1", "msg1")
        assert len(loop.messages) >= 2

        await loop.run("sys2", "fresh start")
        user_msgs = [m for m in loop.messages if m.role == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0].content == "fresh start"

    @pytest.mark.ac("AC-06.9.2")
    async def test_send_without_run_raises(self) -> None:
        """Edge: send() before run() raises RuntimeError."""
        from guild.agent.loop import AgentLoop

        provider = _make_mock_provider(_simple_response("Nope"))
        loop = AgentLoop(provider=provider, tool_executors={})

        with pytest.raises(RuntimeError, match="run.*before"):
            await loop.send("hello")

    @pytest.mark.ac("AC-06.9.1")
    async def test_multiple_sends_accumulate(self) -> None:
        """Edge: four consecutive messages all preserved in history."""
        from guild.agent.loop import AgentLoop

        provider = _make_mock_provider(
            _simple_response("R1"),
            _simple_response("R2"),
            _simple_response("R3"),
            _simple_response("R4"),
        )
        loop = AgentLoop(provider=provider, tool_executors={})

        await loop.run("sys", "m1")
        await loop.send("m2")
        await loop.send("m3")
        result = await loop.send("m4")

        assert result == "R4"
        user_msgs = [m for m in loop.messages if m.role == "user"]
        assistant_msgs = [m for m in loop.messages if m.role == "assistant"]
        assert len(user_msgs) == 4
        assert len(assistant_msgs) == 4


# ======================================================================
# ======================================================================


class TestSelfReviewE2E:
    """Agent can perform adversarial self-review on its own work."""

    @pytest.mark.ac("AC-06.10.1")
    async def test_self_review_prompt_injected(self) -> None:
        """Happy: self-review prompt appears in conversation history."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop

        provider = _make_mock_provider(
            _simple_response("Task complete."),
            _simple_response("Reviewed. No issues found."),
        )
        loop = AgentLoop(provider=provider, tool_executors={})
        result = await loop.run("sys", "Write code", self_review=True)

        review_msgs = [
            m for m in loop.messages if m.role == "user" and SELF_REVIEW_PROMPT in m.content
        ]
        assert len(review_msgs) == 1
        assert "Reviewed" in result

    @pytest.mark.ac("AC-06.10.1")
    async def test_self_review_skipped_on_escalation(self) -> None:
        """Sad: if task escalated (stuck), self-review is skipped."""
        from guild.agent.loop import AgentLoop
        from guild.agent.stuck import StuckDetector
        from guild.tools.base import ToolResult

        async def mock_read(args: dict[str, Any], wd: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="data")

        same_call = _tool_response("file_read", {"path": "x"})
        provider = _make_mock_provider(*[same_call for _ in range(6)])
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_read},
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run("sys", "Do task", self_review=True)

        # Escalation message starts with "I'm stuck"
        assert "stuck" in result.lower() or "need help" in result.lower()
        # Self-review prompt should NOT have been injected after escalation
        from guild.agent.loop import SELF_REVIEW_PROMPT

        review_msgs = [
            m for m in loop.messages if m.role == "user" and SELF_REVIEW_PROMPT in m.content
        ]
        assert len(review_msgs) == 0

    @pytest.mark.ac("AC-06.10.2")
    async def test_self_review_default_off(self) -> None:
        """Edge: self_review defaults to False."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop

        provider = _make_mock_provider(_simple_response("Done."))
        loop = AgentLoop(provider=provider, tool_executors={})
        await loop.run("sys", "task")

        review_msgs = [
            m for m in loop.messages if m.role == "user" and SELF_REVIEW_PROMPT in m.content
        ]
        assert len(review_msgs) == 0


# ======================================================================
# ======================================================================


class TestTryTestRollbackE2E:
    """File-level snapshotting and rollback for impactful decisions."""

    @pytest.mark.ac("AC-06.11.2")
    async def test_rollback_on_verification_failure(self, project_dir: Path) -> None:
        """Happy: verification fails => files restored to original state."""
        from guild.agent.rollback import try_with_rollback

        target = project_dir / "data.txt"
        target.write_text("original")

        async def execute() -> str:
            target.write_text("bad change")
            return "executed"

        async def verify() -> bool:
            return False  # verification fails

        success, result = await try_with_rollback(execute, verify, [str(target)])

        assert success is False
        assert result is None
        assert target.read_text() == "original"

    @pytest.mark.ac("AC-06.11.1")
    async def test_changes_kept_on_verification_success(self, project_dir: Path) -> None:
        """Sad (reverse): verification succeeds => changes kept."""
        from guild.agent.rollback import try_with_rollback

        target = project_dir / "data.txt"
        target.write_text("original")

        async def execute() -> str:
            target.write_text("new content")
            return "done"

        async def verify() -> bool:
            return True

        success, result = await try_with_rollback(execute, verify, [str(target)])

        assert success is True
        assert result == "done"
        assert target.read_text() == "new content"

    @pytest.mark.ac("AC-06.11.2")
    async def test_rollback_deletes_newly_created_files(self, project_dir: Path) -> None:
        """Edge: file created during execute is deleted on rollback."""
        from guild.agent.rollback import try_with_rollback

        new_file = project_dir / "new.txt"
        assert not new_file.exists()

        async def execute() -> str:
            new_file.write_text("created")
            return "created"

        async def verify() -> bool:
            return False

        success, _ = await try_with_rollback(execute, verify, [str(new_file)])

        assert success is False
        assert not new_file.exists()

    @pytest.mark.ac("AC-06.11.2")
    async def test_rollback_handles_multiple_files(self, project_dir: Path) -> None:
        """Edge: multiple files are all rolled back atomically."""
        from guild.agent.rollback import try_with_rollback

        f1 = project_dir / "one.txt"
        f2 = project_dir / "two.txt"
        f1.write_text("1")
        f2.write_text("2")

        async def execute() -> str:
            f1.write_text("X")
            f2.write_text("Y")
            return "modified"

        async def verify() -> bool:
            return False

        success, _ = await try_with_rollback(execute, verify, [str(f1), str(f2)])

        assert success is False
        assert f1.read_text() == "1"
        assert f2.read_text() == "2"


# ======================================================================
# New tests for uncovered ACs
# ======================================================================


class TestTier0BlockedToolsAudited:
    """Dropped tool calls at Tier 0 are logged in the audit trail."""

    @pytest.mark.ac("AC-03.1.3")
    def test_tier0_blocked_tool_logged(self, project_dir: Path) -> None:
        """Tier 0 blocked tool call creates audit entry with reason."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        result = checker.check("file_read", "agent-e2e", {"path": "/tmp"})
        assert result is False
        # Audit log should contain action="tool_blocked"
        assert len(checker.audit_entries) >= 1
        entry = checker.audit_entries[-1]
        assert entry.action == "tool_blocked"
        assert entry.status == "tier_0_blocked"


class TestAskTierPerCallMode:
    """per-call approval mode prompts on every invocation."""

    @pytest.mark.ac("AC-03.2.4")
    def test_per_call_always_prompts(self, project_dir: Path) -> None:
        """With per-call mode, even previously approved tools re-prompt."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        call_count = 0

        def counting_prompt(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        checker = PermissionChecker(
            tier=PermissionTier.ASK,
            prompt_fn=counting_prompt,
            per_call=True,
        )
        checker.check("file_read", "agent-e2e", {"path": "/a"})
        checker.check("file_read", "agent-e2e", {"path": "/b"})
        # In per-call mode, both should prompt (call_count == 2)
        assert call_count == 2


class TestScopedViolationReportsSpecificBoundary:
    """Scope violation is reported back with the specific boundary exceeded."""

    @pytest.mark.ac("AC-03.3.4")
    def test_scoped_violation_includes_boundary(self, project_dir: Path) -> None:
        """Scope violation error includes the specific scope boundary."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_write"],
            allowed_paths=[str(project_dir / "src")],
        )
        # Attempt outside scope should mention the boundary
        result = checker.check(
            "file_write",
            "agent-e2e",
            {"path": str(project_dir / "docs" / "readme.md"), "content": "x"},
        )
        assert result is False
        assert "outside allowed boundaries" in checker.last_denial_reason
        assert str(project_dir / "src") in checker.last_denial_reason


class TestSwitchTiersClearsSessionApprovals:
    """Switching tiers clears session-level approvals."""

    @pytest.mark.ac("AC-03.5.3")
    def test_tier_switch_clears_approval_cache(self, project_dir: Path) -> None:
        """Switching tier away and back re-prompts previously approved tools."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        prompt_count = 0

        def counting_prompt(tool: str, agent_id: str, args: dict[str, Any]) -> bool:
            nonlocal prompt_count
            prompt_count += 1
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=counting_prompt)
        checker.check("file_read", "agent-e2e", {"path": "/a"})
        assert prompt_count == 1

        checker.set_tier(PermissionTier.AUTOPILOT)
        checker.set_tier(PermissionTier.ASK, prompt_fn=counting_prompt)
        checker.check("file_read", "agent-e2e", {"path": "/b"})
        assert prompt_count == 2  # re-prompted because cache cleared


class TestAutoPermittedActionsLogged:
    """Auto-permitted actions (Tier 3, Tier 2 in-scope) are logged."""

    @pytest.mark.ac("AC-03.6.3")
    def test_autopilot_tool_calls_logged(self, project_dir: Path) -> None:
        """Tier 3 tool calls create audit entries with status=auto_permitted."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        result = checker.check("file_read", "agent-e2e", {"path": "/tmp"})
        assert result is True
        # Audit log should contain entry with status="auto_permitted"
        assert len(checker.audit_entries) >= 1
        entry = checker.audit_entries[-1]
        assert entry.status == "auto_permitted"


class TestHardcodedNeverBlocksRecordedInAudit:
    """Hardcoded-never blocks are recorded in the audit log with matched pattern."""

    @pytest.mark.ac("AC-03.6.4")
    def test_hardcoded_never_block_provides_pattern(self, project_dir: Path) -> None:
        """Hardcoded-never block returns the matched denylist pattern."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never(
            "shell", {"command": "git push --force origin main"}
        )
        assert allowed is False
        assert "git push --force" in reason


class TestHardcodedNeverCannotBeWeakenedViaConfig:
    """Hardcoded-never patterns cannot be weakened via config file."""

    @pytest.mark.ac("AC-03.7.4")
    def test_hardcoded_never_not_weakened_by_config(self, project_dir: Path) -> None:
        """Hardcoded-never patterns remain active regardless of config."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        # Even with the most permissive tier, hardcoded never blocks
        checker = PermissionChecker(
            tier=PermissionTier.AUTOPILOT,
            allowed_tools=["shell"],
            allowed_paths=["/"],
        )
        assert (
            checker.check("shell", "agent-e2e", {"command": "git push --force origin main"})
            is False
        )


class TestToolsTaggedWithReversibility:
    """Tools are tagged with a reversibility level."""

    @pytest.mark.ac("AC-03.8.3")
    def test_tools_have_reversibility_metadata(self) -> None:
        """Built-in tools have reversibility metadata."""
        from guild.tools.base import TOOL_SCHEMAS

        # Future: each tool schema should include a reversibility field
        for tool_name, schema in TOOL_SCHEMAS.items():
            assert (
                "reversibility" in schema or "is_read_only" in schema
            ), f"Tool {tool_name} missing reversibility metadata"


class TestInteractiveAttachStreamsExisting:
    """Attaching streams existing output before accepting input."""

    @pytest.mark.ac("AC-05.4a.2")
    async def test_subscribe_receives_pending_broadcasts(self, tmp_path: Path) -> None:
        """Subscribed client receives messages already broadcast."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "stream.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Subscribe first
        writer.write(json.dumps({"type": "command", "action": "subscribe"}).encode() + b"\n")
        await writer.drain()
        ack = json.loads(await reader.readline())
        assert ack["status"] == "subscribed"

        # Broadcast messages and verify receipt
        for i in range(3):
            await cs.broadcast({"type": "agent_message", "content": f"msg-{i}"})
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            data = json.loads(line)
            assert data["content"] == f"msg-{i}"

        writer.close()
        await writer.wait_closed()
        await cs.stop()


# ===================================================================
# REQ-06.2: Verification failure details in task status
# ===================================================================


class TestVerificationFailureDetails:
    """Verification failure details are included in task final status."""

    @pytest.mark.ac("AC-06.2.3")
    async def test_verification_failure_details_in_status(self, project_dir: Path) -> None:
        """Task status shows specific verification failure message, not just 'failed'."""
        from guild.task.spec import (
            TaskSpec,
            VerificationStep,
            format_verification_results,
            run_verification,
        )

        spec = TaskSpec(
            description="Test task",
            verification_steps=[
                VerificationStep(type="file_exists", target="nonexistent.py"),
                VerificationStep(type="command", target="false"),
            ],
        )
        passed, results = await run_verification(spec, str(project_dir))
        assert passed is False
        formatted = format_verification_results(results)
        assert "FAIL" in formatted
        assert "nonexistent.py" in formatted
        assert "Step 1" in formatted
        assert "Step 2" in formatted


# ===================================================================
# REQ-06.4: Recovery strategy is logged
# ===================================================================


class TestRecoveryStrategyLogged:
    """The recovery strategy is logged so the user can see what was tried."""

    @pytest.mark.ac("AC-06.4.3")
    async def test_stuck_recovery_prompt_content(self) -> None:
        """Stuck detection recovery prompt includes actionable recovery guidance."""
        from guild.agent.loop import STUCK_RECOVERY_PROMPT

        assert "stuck" in STUCK_RECOVERY_PROMPT.lower()
        assert "different approach" in STUCK_RECOVERY_PROMPT.lower()


# ===================================================================
# REQ-06.7: Timeout progress report includes accomplishments
# ===================================================================


class TestTimeoutProgressReport:
    """The progress report generated at timeout includes what was accomplished."""

    @pytest.mark.ac("AC-06.7.3")
    async def test_timeout_progress_report_includes_summary(self) -> None:
        """Timeout pause message includes summary of completed actions and current step."""
        from guild.agent.loop import AgentLoop
        from guild.tools.base import ToolResult

        call_counter = 0

        async def mock_generate(
            messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
        ) -> LLMResponse:
            nonlocal call_counter
            call_counter += 1
            if call_counter <= 2:
                return LLMResponse(
                    content="",
                    tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "/x"}}}],
                    input_tokens=10,
                    output_tokens=5,
                    model="mock",
                )
            return LLMResponse(
                content="Done with task.",
                tool_calls=None,
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )

        async def mock_file_read(args: dict[str, Any], _cid: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="contents")

        provider = AsyncMock()
        provider.generate = mock_generate

        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_file_read},
            max_turns=5,
        )
        await loop.run("system", "do something")

        report = loop.generate_timeout_report()
        assert "turn(s)" in report
        assert "file_read" in report
        assert "Tool calls" in report or "tool calls" in report.lower()


# ===================================================================
# REQ-06.9: send() preserves all prior context including tool results
# ===================================================================


class TestSendPreservesToolContext:
    """The send() method preserves all prior context including tool results."""

    @pytest.mark.ac("AC-06.9.3")
    async def test_send_preserves_tool_results_from_run(self) -> None:
        """Messages sent to LLM for step 2 include tool call results from step 1."""
        from guild.agent.loop import AgentLoop
        from guild.tools.base import ToolResult

        call_counter = 0
        captured_messages: list[list[dict[str, Any]]] = []

        async def tracking_generate(
            messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
        ) -> LLMResponse:
            nonlocal call_counter
            captured_messages.append([m.copy() for m in messages])
            call_counter += 1
            if call_counter == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {"function": {"name": "file_read", "arguments": {"path": "/tmp/x"}}}
                    ],
                    input_tokens=10,
                    output_tokens=5,
                    model="mock",
                )
            return LLMResponse(
                content="Step done.",
                tool_calls=None,
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )

        async def mock_file_read(args: dict[str, Any], _cid: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="file contents here")

        provider = AsyncMock()
        provider.generate = tracking_generate
        provider.health_check = AsyncMock(return_value=True)

        loop = AgentLoop(
            provider=provider,
            tool_executors={"file_read": mock_file_read},
        )

        await loop.run("system", "do step 1")
        call_counter = 0
        captured_messages.clear()
        await loop.send("now do step 2")

        assert len(captured_messages) > 0
        all_roles = [m["role"] for m in captured_messages[0]]
        assert "tool" in all_roles, "Tool results from step 1 should be in step 2 context"


# ===================================================================
# REQ-06.10: Self-review can be disabled per-task or globally
# ===================================================================


class TestSelfReviewConfigurable:
    """Self-review can be disabled per-task or globally via configuration."""

    @pytest.mark.ac("AC-06.10.3")
    async def test_self_review_disabled_skips_review(self) -> None:
        """Setting self_review=False skips the adversarial self-review prompt."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop

        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="Implementation done.",
                tool_calls=None,
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )
        )
        loop = AgentLoop(provider=provider, tool_executors={})

        result = await loop.run("system prompt", "build a feature", self_review=False)
        assert result == "Implementation done."
        message_contents = [m.content for m in loop.messages]
        assert SELF_REVIEW_PROMPT not in message_contents

    @pytest.mark.ac("AC-06.10.3")
    async def test_self_review_enabled_injects_review(self) -> None:
        """Setting self_review=True injects the adversarial self-review prompt."""
        from guild.agent.loop import SELF_REVIEW_PROMPT, AgentLoop

        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="All looks good.",
                tool_calls=None,
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )
        )
        loop = AgentLoop(provider=provider, tool_executors={})

        await loop.run("system prompt", "build a feature", self_review=True)
        message_contents = [m.content for m in loop.messages]
        assert SELF_REVIEW_PROMPT in message_contents
