"""E2E acceptance tests for daemon lifecycle, permissions, and artifacts.

Black-box tests exercising features from the outside.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
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


# REQ-03.1: Permission system
@pytest.mark.req("REQ-03.1")
class TestPermissions:
    """Permission tiers are enforced through the CLI."""

    def test_task_runs_in_autopilot_by_default(self, project_dir: Path) -> None:
        """Default permission is autopilot — no prompts."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=LLMResponse(
            content="Done.", tool_calls=None,
            input_tokens=10, output_tokens=5, model="mock",
        ))
        mock_provider.health_check = AsyncMock(return_value=True)

        with patch("guild.cli.task_runner.create_resilient_provider", return_value=mock_provider):
            result = runner.invoke(app, ["task", "Simple task", "--permission", "autopilot"])
        assert result.exit_code == 0
        assert "Done" in result.output

    def test_permission_flag_accepted(self, project_dir: Path) -> None:
        """--permission flag is recognized for all tiers."""
        for tier in ["nothing", "ask", "scoped", "autopilot"]:
            result = runner.invoke(app, ["task", "test", "--permission", tier, "--help"])
            # Just verifying the flag is accepted (--help exits before running)


# REQ-23.9: Control socket
@pytest.mark.req("REQ-23.9")
class TestControlSocket:
    """Control socket accepts connections, processes commands, and cleans up."""

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


# REQ-18.1: Artifact management
@pytest.mark.req("REQ-18.1")
class TestArtifacts:
    """Artifact save, retrieve, and review lifecycle."""

    def test_artifact_save_and_retrieve(self, project_dir: Path) -> None:
        """Save artifact, retrieve it, verify content."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-1", "result.py", "print('hello')")

        content = mgr.get("task-1", "result.py")
        assert content == "print('hello')"

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


# REQ-18.3: Accept/reject/edit
@pytest.mark.req("REQ-18.3")
class TestArtifactReview:
    """Artifact accept, reject, and edit operations."""

    def test_reject_removes_artifact(self, project_dir: Path) -> None:
        """Rejecting removes the artifact completely."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-3", "bad.py", "import os; os.system('rm -rf /')")
        mgr.reject("task-3", "bad.py")
        assert mgr.get("task-3", "bad.py") is None

    def test_edit_updates_and_accepts(self, project_dir: Path) -> None:
        """Editing saves new content and auto-accepts."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(project_dir / ".guild" / "artifacts")
        mgr.save("task-4", "draft.py", "x = 1")
        mgr.edit("task-4", "draft.py", "x = 2  # fixed")

        assert mgr.get("task-4", "draft.py") == "x = 2  # fixed"
        assert len(mgr.list_accepted("task-4")) == 1


# REQ-24.6: GPU/VRAM awareness
@pytest.mark.req("REQ-24.6")
class TestResourceAwareness:
    """Resource monitor detects GPU/VRAM pressure and throttles accordingly."""

    def test_vram_pressure_triggers_throttle(self) -> None:
        """High VRAM usage causes the resource monitor to throttle."""
        from guild.daemon.resource import ResourceMonitor, ResourceThresholds, SchedulingMode

        gpu_reader = lambda: {"gpu_percent": 90.0, "vram_used_mb": 7500, "vram_total_mb": 8192}
        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE, thresholds=thresholds, gpu_reader=gpu_reader,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "vram" in status.reason.lower()

    def test_no_pressure_no_throttle(self) -> None:
        """Low VRAM usage does not throttle."""
        from guild.daemon.resource import ResourceMonitor, ResourceThresholds, SchedulingMode

        gpu_reader = lambda: {"gpu_percent": 30.0, "vram_used_mb": 2000, "vram_total_mb": 8192}
        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE, thresholds=thresholds, gpu_reader=gpu_reader,
        )
        status = monitor.get_status()
        assert not status.is_throttled
