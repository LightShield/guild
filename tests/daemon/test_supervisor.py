"""Tests for daemon/supervisor.py — daemon lifecycle management (REQ-23, REQ-25)."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.daemon.supervisor import DaemonSupervisor


@pytest.mark.unit
@pytest.mark.req("REQ-23.2")
class TestPidFile:
    """PID file creation and removal."""

    async def test_creates_pid_file_on_start(self, tmp_path: Path) -> None:
        """Supervisor creates a PID file when run() is called."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-001")

        async def noop() -> str:
            return "done"

        await supervisor.run(noop())
        # PID file should have been created (then removed on clean exit)
        # Verify the directory was created
        assert run_dir.exists()

    async def test_removes_pid_file_on_stop(self, tmp_path: Path) -> None:
        """Supervisor removes PID file after run() completes."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-002")

        async def noop() -> str:
            return "done"

        await supervisor.run(noop())
        assert not supervisor.pid_path.exists()

    async def test_pid_file_contains_process_id(self, tmp_path: Path) -> None:
        """PID file contains the current process PID as text."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-003")
        pid_content: str | None = None

        async def capture_pid() -> str:
            nonlocal pid_content
            pid_content = supervisor.pid_path.read_text().strip()
            return "done"

        await supervisor.run(capture_pid())
        assert pid_content == str(os.getpid())


@pytest.mark.unit
@pytest.mark.req("REQ-23.6")
class TestSupervisorExecution:
    """Supervisor runs the agent coroutine and handles exceptions."""

    async def test_supervisor_runs_agent_loop(self, tmp_path: Path) -> None:
        """Supervisor executes the provided coroutine and returns its result."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-004")

        async def agent_work() -> str:
            return "task completed"

        result = await supervisor.run(agent_work())
        assert result == "task completed"

    async def test_supervisor_catches_agent_exceptions(self, tmp_path: Path) -> None:
        """Supervisor logs exceptions and re-raises; PID file is still cleaned up."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-005")

        async def failing_agent() -> str:
            raise RuntimeError("agent crashed")

        with pytest.raises(RuntimeError, match="agent crashed"):
            await supervisor.run(failing_agent())

        # PID file should be removed even after exception
        assert not supervisor.pid_path.exists()


@pytest.mark.unit
@pytest.mark.req("REQ-23.8")
class TestForegroundMode:
    """Foreground mode blocks until the coroutine completes."""

    async def test_foreground_mode_blocks_until_complete(self, tmp_path: Path) -> None:
        """run() blocks until the coroutine finishes (foreground behavior)."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-006")
        sequence: list[str] = []

        async def slow_task() -> str:
            sequence.append("started")
            await asyncio.sleep(0.05)
            sequence.append("finished")
            return "result"

        result = await supervisor.run(slow_task())
        assert sequence == ["started", "finished"]
        assert result == "result"


@pytest.mark.unit
@pytest.mark.req("REQ-25.4")
class TestSignalHandling:
    """SIGTERM and SIGINT trigger graceful shutdown."""

    async def test_sigterm_triggers_graceful_shutdown(self, tmp_path: Path) -> None:
        """SIGTERM sets the shutdown_requested flag."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-007")
        shutdown_seen = False

        async def check_shutdown() -> str:
            nonlocal shutdown_seen
            # Install handlers first (run does this internally, but we need
            # to send signal during execution)
            await asyncio.sleep(0)
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)
            shutdown_seen = supervisor.shutdown_requested
            return "done"

        await supervisor.run(check_shutdown())
        assert shutdown_seen is True

    async def test_sigint_triggers_graceful_shutdown(self, tmp_path: Path) -> None:
        """SIGINT sets the shutdown_requested flag."""
        run_dir = tmp_path / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-008")
        shutdown_seen = False

        async def check_shutdown() -> str:
            nonlocal shutdown_seen
            await asyncio.sleep(0)
            os.kill(os.getpid(), signal.SIGINT)
            await asyncio.sleep(0.01)
            shutdown_seen = supervisor.shutdown_requested
            return "done"

        await supervisor.run(check_shutdown())
        assert shutdown_seen is True

    async def test_sigterm_sets_shutdown_flag(self, tmp_path: Path) -> None:
        """SIGTERM sets the flag even without on_checkpoint callback."""
        run_dir = tmp_path / "run"
        # No on_checkpoint callback
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id="task-sigterm")

        # Initially not set
        assert supervisor.shutdown_requested is False

        async def send_signal_and_check() -> str:
            await asyncio.sleep(0)
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)
            return "done"

        await supervisor.run(send_signal_and_check())
        # Flag persists after run() completes
        assert supervisor.shutdown_requested is True


@pytest.mark.unit
@pytest.mark.req("REQ-25.6")
class TestStatePersistence:
    """State is persisted before shutdown."""

    async def test_state_persisted_before_shutdown(self, tmp_path: Path) -> None:
        """on_checkpoint callback is invoked during graceful shutdown."""
        run_dir = tmp_path / "run"
        checkpoint_called = False

        async def on_checkpoint() -> None:
            nonlocal checkpoint_called
            checkpoint_called = True

        supervisor = DaemonSupervisor(
            run_dir=run_dir,
            task_id="task-009",
            on_checkpoint=on_checkpoint,
        )

        async def trigger_shutdown() -> str:
            await asyncio.sleep(0)
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.01)
            return "done"

        await supervisor.run(trigger_shutdown())
        assert checkpoint_called is True
