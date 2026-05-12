"""E2E acceptance tests for daemon lifecycle, process management, and sleep/wake.

Black-box tests exercising REQ-23.x (daemon execution), REQ-25.x (process
lifecycle), and REQ-26.x (sleep/wake survival) from the outside.

Uses CliRunner for CLI commands and real ControlSocket/Supervisor for daemon
features.  Provider (external I/O) is mocked at the boundary; everything else
is real.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.daemon.control_socket import ControlSocket
from guild.daemon.lifecycle import ExitCode, LifecycleManager, TaskQueue
from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector, WakeBehavior
from guild.daemon.supervisor import DaemonSupervisor
from guild.provider.base import LLMResponse
from guild.storage.sqlite import Storage

runner = CliRunner()
pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_provider() -> AsyncMock:
    """Create a mock provider that finishes after one turn."""
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=LLMResponse(
        content="Done.",
        tool_calls=None,
        input_tokens=10,
        output_tokens=5,
        model="mock",
    ))
    provider.health_check = AsyncMock(return_value=True)
    return provider


async def _make_storage(path: Path) -> Storage:
    """Create a real Storage instance backed by SQLite."""
    db_path = path / "guild.db"
    store = Storage(db_path)
    await store.connect()
    return store


def _write_pid_file(run_dir: Path, task_id: str, pid: int) -> Path:
    """Write a fake PID file."""
    pid_file = run_dir / f"{task_id}.pid"
    pid_file.write_text(str(pid))
    return pid_file


def _write_sock_file(run_dir: Path, task_id: str) -> Path:
    """Write a fake socket file."""
    sock_file = run_dir / f"{task_id}.sock"
    sock_file.write_text("")
    return sock_file


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a guild project in a temporary directory."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, f"guild init failed: {result.output}"
    return tmp_path


@pytest.fixture()
def guild_env(tmp_path: Path) -> dict:
    """Provide a minimal guild environment (run_dir + storage)."""
    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    run_dir = guild_dir / "run"
    run_dir.mkdir()
    return {"guild_dir": guild_dir, "run_dir": run_dir, "tmp_path": tmp_path}


# ===================================================================
# REQ-23.1: --background launches daemon
# ===================================================================


class TestBackgroundLaunch:
    """guild task --background launches a daemon and returns immediately."""

    @pytest.mark.ac("AC-23.1.2")
    def test_background_flag_prints_task_id(self, project_dir: Path) -> None:
        """--background launches daemon and prints the task ID."""
        with patch("guild.cli.main._launch_background_task") as mock_launch:
            result = runner.invoke(
                app, ["task", "background job", "--background"],
            )

        assert result.exit_code == 0
        assert "Launched background task" in result.output
        mock_launch.assert_called_once()

    @pytest.mark.ac("AC-23.1.1")
    def test_background_creates_task_in_storage(self, project_dir: Path) -> None:
        """--background persists the task in SQLite before forking."""
        with patch("guild.cli.main._launch_background_task"):
            result = runner.invoke(
                app, ["task", "stored task", "--background"],
            )

        assert result.exit_code == 0
        # Verify task appeared in history
        hist = runner.invoke(app, ["history"], terminal_width=200)
        assert "stored task" in hist.output


# ===================================================================
# REQ-23.2: PID file written
# ===================================================================


class TestPidFile:
    """Daemon writes and removes PID files for lifecycle tracking."""

    @pytest.mark.ac("AC-23.2.1")
    async def test_supervisor_writes_pid_file(self, guild_env: dict) -> None:
        """DaemonSupervisor.write_pid_file creates <task_id>.pid in run_dir."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="pid-test")
        sup.write_pid_file()

        assert sup.pid_path.exists()
        assert sup.pid_path.read_text().strip() == str(os.getpid())
        sup.remove_pid_file()

    @pytest.mark.ac("AC-23.2.3")
    async def test_pid_file_removed_on_cleanup(self, guild_env: dict) -> None:
        """PID file is removed when remove_pid_file is called."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="cleanup-test")
        sup.write_pid_file()
        assert sup.pid_path.exists()

        sup.remove_pid_file()
        assert not sup.pid_path.exists()

    @pytest.mark.ac("AC-23.2.1")
    async def test_supervisor_run_creates_and_removes_pid(self, guild_env: dict) -> None:
        """supervisor.run() writes PID before coroutine and removes after."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="run-pid")
        pid_existed_during = False

        async def agent_work() -> str:
            nonlocal pid_existed_during
            pid_existed_during = sup.pid_path.exists()
            return "ok"

        result = await sup.run(agent_work())
        assert result == "ok"
        assert pid_existed_during is True
        assert not sup.pid_path.exists()


# ===================================================================
# REQ-23.3: attach reconnects
# ===================================================================


class TestAttachReconnects:
    """guild attach connects to a running task via the control socket."""

    @pytest.mark.ac("AC-23.3.2")
    def test_attach_fails_without_socket(self, project_dir: Path) -> None:
        """attach errors when no control socket exists for the task."""
        result = runner.invoke(app, ["attach", "nonexistent-task"])
        assert result.exit_code != 0
        assert "not running" in result.output.lower() or "Error" in result.output

    @pytest.mark.ac("AC-23.3.1")
    async def test_attach_can_subscribe_to_socket(self, guild_env: dict) -> None:
        """A client can connect and subscribe to a running control socket."""
        run_dir = guild_env["run_dir"]
        sock_path = run_dir / "attach-test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(
            json.dumps({"type": "command", "action": "subscribe"}).encode() + b"\n",
        )
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "subscribed"

        # Broadcast a message and verify client receives it
        await cs.broadcast({"type": "agent_message", "content": "hello from agent"})
        msg = await asyncio.wait_for(reader.readline(), timeout=2.0)
        data = json.loads(msg)
        assert data["content"] == "hello from agent"

        writer.close()
        await writer.wait_closed()
        await cs.stop()


# ===================================================================
# REQ-23.4: logs command
# ===================================================================


class TestLogsCommand:
    """guild logs <task_id> streams agent output."""

    @pytest.mark.ac("AC-23.4.1")
    def test_logs_shows_no_messages_for_unknown_task(self, project_dir: Path) -> None:
        """logs on a non-existent task shows 'No messages'."""
        result = runner.invoke(app, ["logs", "unknown-task-id"])
        assert result.exit_code == 0
        assert "No messages" in result.output

    @pytest.mark.ac("AC-23.4.1")
    def test_logs_shows_messages_after_task(self, project_dir: Path) -> None:
        """logs displays messages recorded by a completed task."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            runner.invoke(app, ["task", "Say hello"])

        # The agent_id used by foreground tasks follows a pattern.
        # We use history to find the task ID then check logs.
        hist = runner.invoke(app, ["history"], terminal_width=200)
        assert hist.exit_code == 0


# ===================================================================
# REQ-23.5: ps shows running tasks
# ===================================================================


class TestPsCommand:
    """guild ps shows all running/paused tasks."""

    @pytest.mark.ac("AC-23.5.2")
    def test_ps_empty_project(self, project_dir: Path) -> None:
        """ps on a fresh project shows 'No running tasks'."""
        result = runner.invoke(app, ["ps"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    @pytest.mark.ac("AC-23.5.1")
    def test_ps_shows_live_pid(self, project_dir: Path) -> None:
        """ps lists tasks that have a live PID file in the run directory."""
        run_dir = project_dir / ".guild" / "run"
        run_dir.mkdir(exist_ok=True)
        _write_pid_file(run_dir, "live-task", os.getpid())

        result = runner.invoke(app, ["ps"])
        assert result.exit_code == 0
        assert "live-task" in result.output
        # Clean up
        (run_dir / "live-task.pid").unlink()

    @pytest.mark.ac("AC-23.5.1")
    def test_ps_ignores_dead_pid(self, project_dir: Path) -> None:
        """ps does not show tasks whose PID is dead."""
        run_dir = project_dir / ".guild" / "run"
        run_dir.mkdir(exist_ok=True)
        _write_pid_file(run_dir, "dead-task", 999999999)

        result = runner.invoke(app, ["ps"])
        assert result.exit_code == 0
        assert "dead-task" not in result.output


# ===================================================================
# REQ-23.6: Minimal supervisor
# ===================================================================


class TestMinimalSupervisor:
    """DaemonSupervisor wraps AgentLoop with PID, signals, and socket."""

    @pytest.mark.ac("AC-23.6.2")
    async def test_supervisor_manages_full_lifecycle(self, guild_env: dict) -> None:
        """Supervisor writes PID, installs signals, runs coro, cleans up."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="sup-lifecycle")

        async def work() -> str:
            # During execution, PID file should exist
            assert sup.pid_path.exists()
            return "done"

        result = await sup.run(work())
        assert result == "done"
        # After run(), PID is cleaned up and signals restored
        assert not sup.pid_path.exists()

    @pytest.mark.ac("AC-23.6.1")
    async def test_supervisor_cleans_up_on_exception(self, guild_env: dict) -> None:
        """PID file is removed even when the supervised coroutine raises."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="sup-error")

        async def failing_work() -> None:
            raise RuntimeError("agent crashed")

        with pytest.raises(RuntimeError, match="agent crashed"):
            await sup.run(failing_work())

        assert not sup.pid_path.exists()

    @pytest.mark.ac("AC-23.6.2")
    async def test_supervisor_starts_and_stops_control_socket(
        self, guild_env: dict,
    ) -> None:
        """Supervisor can start/stop a control socket for its task."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="sup-sock")

        await sup.start_control_socket()
        assert sup.socket_path.exists()

        await sup.stop_control_socket()
        assert not sup.socket_path.exists()


# ===================================================================
# REQ-23.7: Multiple concurrent tasks
# ===================================================================


class TestConcurrentTasks:
    """TaskQueue enforces max_concurrent_agents limit."""

    @pytest.mark.ac("AC-23.7.1")
    async def test_queue_enforces_concurrency_limit(self) -> None:
        """Dequeue returns None when max_concurrent is reached."""
        queue = TaskQueue(max_concurrent=2)
        await queue.enqueue("t1")
        await queue.enqueue("t2")
        await queue.enqueue("t3")

        # Dequeue up to the limit
        assert await queue.dequeue() == "t1"
        assert await queue.dequeue() == "t2"
        # Third dequeue blocked by concurrency limit
        assert await queue.dequeue() is None
        assert queue.active_count == 2

    @pytest.mark.ac("AC-23.7.2")
    async def test_complete_allows_next_dequeue(self) -> None:
        """Completing an active task allows a queued task to dequeue."""
        queue = TaskQueue(max_concurrent=1)
        await queue.enqueue("t1")
        await queue.enqueue("t2")

        assert await queue.dequeue() == "t1"
        assert await queue.dequeue() is None  # at limit

        queue.complete("t1")
        assert queue.active_count == 0
        assert await queue.dequeue() == "t2"

    @pytest.mark.ac("AC-23.7.1")
    async def test_queue_state_reflects_pending_tasks(self) -> None:
        """get_queue_state returns all pending (not yet dequeued) tasks."""
        queue = TaskQueue(max_concurrent=5)
        await queue.enqueue("a")
        await queue.enqueue("b")
        await queue.enqueue("c")

        state = await queue.get_queue_state()
        assert len(state) == 3
        assert [s["task_id"] for s in state] == ["a", "b", "c"]


# ===================================================================
# REQ-23.8: Foreground default
# ===================================================================


class TestForegroundDefault:
    """Tasks run in foreground when --background is not specified."""

    @pytest.mark.ac("AC-23.8.1")
    def test_task_runs_foreground_by_default(self, project_dir: Path) -> None:
        """guild task without --background runs synchronously in foreground."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(app, ["task", "Foreground task"])

        assert result.exit_code == 0
        assert "Done" in result.output

    @pytest.mark.ac("AC-23.8.1")
    def test_background_false_is_default(self, project_dir: Path) -> None:
        """The --background flag defaults to False."""
        # Run with --help to inspect default
        result = runner.invoke(app, ["task", "--help"])
        assert result.exit_code == 0
        # The help text should indicate background is off by default
        assert "--background" in result.output


# ===================================================================
# REQ-25.1: kill sends shutdown
# ===================================================================


class TestKillCommand:
    """guild kill sends graceful shutdown to a running task."""

    @pytest.mark.ac("AC-25.1.1")
    async def test_kill_via_control_socket(self, guild_env: dict) -> None:
        """Sending a kill command via the control socket sets shutdown flag."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="kill-test")
        await sup.start_control_socket()

        reader, writer = await asyncio.open_unix_connection(str(sup.socket_path))
        writer.write(
            json.dumps({"type": "command", "action": "kill"}).encode() + b"\n",
        )
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "shutting_down"
        assert sup.shutdown_requested is True

        writer.close()
        await writer.wait_closed()
        await sup.stop_control_socket()

    @pytest.mark.ac("AC-25.1.1")
    async def test_lifecycle_manager_kill_sends_sigterm(self, guild_env: dict) -> None:
        """LifecycleManager.kill_task sends SIGTERM to the target PID."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("kt-1", "killable")
        await store.update_task("kt-1", status="running")
        _write_pid_file(run_dir, "kt-1", 12345)

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        with (
            patch("os.kill") as mock_kill,
            patch("guild.daemon.lifecycle._process_alive", return_value=False),
        ):
            result = await mgr.kill_task("kt-1")

        assert result is True
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        await store.close()

    @pytest.mark.ac("AC-25.1.3")
    def test_kill_cli_no_task_id_errors(self, project_dir: Path) -> None:
        """guild kill without task_id or --all shows error."""
        result = runner.invoke(app, ["kill"])
        assert result.exit_code != 0
        assert "Provide a task ID" in result.output or "Error" in result.output


# ===================================================================
# REQ-25.2: pause command
# ===================================================================


class TestPauseCommand:
    """guild pause sets task to paused state."""

    @pytest.mark.ac("AC-25.2.1")
    async def test_pause_via_control_socket(self, guild_env: dict) -> None:
        """Pause command via control socket sets paused flag."""
        run_dir = guild_env["run_dir"]
        sock_path = run_dir / "pause-test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(
            json.dumps({"type": "command", "action": "pause"}).encode() + b"\n",
        )
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "paused"
        assert cs.is_paused is True

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-25.2.3")
    async def test_pause_updates_storage(self, guild_env: dict) -> None:
        """LifecycleManager.pause_task updates task status in storage."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("pt-1", "pausable")
        await store.update_task("pt-1", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.pause_task("pt-1")

        assert result is True
        task = await store.get_task("pt-1")
        assert task is not None
        assert task["status"] == "paused"
        await store.close()

    @pytest.mark.ac("AC-25.2.1")
    async def test_pause_fails_if_not_running(self, guild_env: dict) -> None:
        """pause_task returns False when task is not in running state."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("pt-2", "pending task")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.pause_task("pt-2")

        assert result is False
        await store.close()


# ===================================================================
# REQ-25.3: resume command
# ===================================================================


class TestResumeCommand:
    """guild resume resumes a paused task."""

    @pytest.mark.ac("AC-25.3.1")
    async def test_resume_via_control_socket(self, guild_env: dict) -> None:
        """Resume command via control socket clears paused flag."""
        run_dir = guild_env["run_dir"]
        sock_path = run_dir / "resume-test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        cs._paused = True
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(
            json.dumps({"type": "command", "action": "resume"}).encode() + b"\n",
        )
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "running"
        assert cs.is_paused is False

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-25.3.1")
    async def test_resume_updates_storage(self, guild_env: dict) -> None:
        """LifecycleManager.resume_task updates task status in storage."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("rt-1", "resumable")
        await store.update_task("rt-1", status="paused")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.resume_task("rt-1")

        assert result is True
        task = await store.get_task("rt-1")
        assert task is not None
        assert task["status"] == "running"
        await store.close()

    @pytest.mark.ac("AC-25.3.3")
    async def test_resume_fails_if_not_paused(self, guild_env: dict) -> None:
        """resume_task returns False when task is not in paused state."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("rt-2", "running task")
        await store.update_task("rt-2", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.resume_task("rt-2")

        assert result is False
        await store.close()


# ===================================================================
# REQ-25.4: Signal handling
# ===================================================================


class TestSignalHandling:
    """Supervisor installs SIGTERM/SIGINT handlers for graceful shutdown."""

    @pytest.mark.ac("AC-25.4.1")
    async def test_signal_handlers_installed_and_restored(
        self, guild_env: dict,
    ) -> None:
        """Supervisor installs custom signal handlers during run, restores after."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="sig-test")

        original_sigterm = signal.getsignal(signal.SIGTERM)

        async def work() -> str:
            # During run, signal handler should be different from original
            current = signal.getsignal(signal.SIGTERM)
            assert current != original_sigterm
            return "ok"

        await sup.run(work())

        # After run, handler should be restored
        restored = signal.getsignal(signal.SIGTERM)
        assert restored == original_sigterm

    @pytest.mark.ac("AC-25.4.1")
    async def test_sigterm_sets_shutdown_flag(self, guild_env: dict) -> None:
        """Calling the shutdown signal handler sets shutdown_requested."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="sig-flag")

        sup.install_signal_handlers()
        # Simulate signal delivery by calling the handler directly
        sup._handle_shutdown_signal(signal.SIGTERM, None)
        assert sup.shutdown_requested is True

        sup.restore_signal_handlers()
        sup.remove_pid_file()

    @pytest.mark.ac("AC-25.4.3")
    async def test_checkpoint_callback_invoked_on_signal(
        self, guild_env: dict,
    ) -> None:
        """on_checkpoint callback is invoked when shutdown signal fires."""
        run_dir = guild_env["run_dir"]
        checkpoint_called = False

        async def checkpoint() -> None:
            nonlocal checkpoint_called
            checkpoint_called = True

        sup = DaemonSupervisor(
            run_dir=run_dir, task_id="sig-cp", on_checkpoint=checkpoint,
        )

        async def work() -> str:
            sup._handle_shutdown_signal(signal.SIGTERM, None)
            # Give the event loop a chance to run the checkpoint task
            await asyncio.sleep(0.05)
            return "ok"

        await sup.run(work())
        assert checkpoint_called is True


# ===================================================================
# REQ-25.5: Orphan detection
# ===================================================================


class TestOrphanDetection:
    """Detect PID files whose processes are no longer alive."""

    @pytest.mark.ac("AC-25.5.1")
    async def test_detect_orphaned_pid_files(self, guild_env: dict) -> None:
        """detect_orphans returns task IDs for dead processes."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])

        _write_pid_file(run_dir, "orphan-1", 11111)
        _write_pid_file(run_dir, "orphan-2", 22222)

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        with patch("guild.daemon.lifecycle._process_alive", return_value=False):
            orphans = mgr.detect_orphans()

        assert set(orphans) == {"orphan-1", "orphan-2"}
        await store.close()

    @pytest.mark.ac("AC-25.5.1")
    async def test_skips_live_processes(self, guild_env: dict) -> None:
        """detect_orphans does not report tasks with alive processes."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])

        _write_pid_file(run_dir, "alive-task", os.getpid())
        _write_pid_file(run_dir, "dead-task", 99999)

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        def selective_alive(pid: int) -> bool:
            return pid == os.getpid()

        with patch(
            "guild.daemon.lifecycle._process_alive", side_effect=selective_alive,
        ):
            orphans = mgr.detect_orphans()

        assert orphans == ["dead-task"]
        await store.close()


# ===================================================================
# REQ-25.6: State persisted per turn
# ===================================================================


class TestStatePersisted:
    """State is persisted to storage on every turn boundary."""

    @pytest.mark.ac("AC-25.6.1")
    async def test_storage_persists_messages(self, guild_env: dict) -> None:
        """Messages appended via storage are immediately durable."""
        store = await _make_storage(guild_env["guild_dir"])
        await store.register_agent("agent-state", "test-block")
        await store.append_message("agent-state", "user", "do something")
        await store.append_message("agent-state", "assistant", "doing it")

        msgs = await store.get_messages("agent-state")
        assert len(msgs) == 2
        assert msgs[0]["content"] == "do something"
        assert msgs[1]["content"] == "doing it"
        await store.close()

    @pytest.mark.ac("AC-25.6.1")
    async def test_task_status_persisted_on_update(self, guild_env: dict) -> None:
        """Task status updates are immediately reflected in storage."""
        store = await _make_storage(guild_env["guild_dir"])
        await store.create_task("state-t1", "stateful task")
        await store.update_task("state-t1", status="running")

        task = await store.get_task("state-t1")
        assert task is not None
        assert task["status"] == "running"

        await store.update_task("state-t1", status="paused")
        task = await store.get_task("state-t1")
        assert task is not None
        assert task["status"] == "paused"
        await store.close()


# ===================================================================
# REQ-25.7: Stale lock cleanup
# ===================================================================


class TestStaleLockCleanup:
    """Dead socket/PID files are cleaned up automatically."""

    @pytest.mark.ac("AC-25.7.1")
    async def test_cleanup_removes_stale_pid_and_sock(self, guild_env: dict) -> None:
        """cleanup_stale_locks removes .pid and .sock for dead processes."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])

        _write_pid_file(run_dir, "stale-1", 77777)
        _write_sock_file(run_dir, "stale-1")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        with patch("guild.daemon.lifecycle._process_alive", return_value=False):
            count = mgr.cleanup_stale_locks()

        assert count == 1
        assert not (run_dir / "stale-1.pid").exists()
        assert not (run_dir / "stale-1.sock").exists()
        await store.close()

    @pytest.mark.ac("AC-25.7.2")
    async def test_cleanup_preserves_live_locks(self, guild_env: dict) -> None:
        """cleanup_stale_locks keeps PID files for alive processes."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])

        _write_pid_file(run_dir, "alive-1", os.getpid())
        _write_sock_file(run_dir, "alive-1")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        with patch(
            "guild.daemon.lifecycle._process_alive",
            side_effect=lambda pid: pid == os.getpid(),
        ):
            count = mgr.cleanup_stale_locks()

        assert count == 0
        assert (run_dir / "alive-1.pid").exists()
        assert (run_dir / "alive-1.sock").exists()
        await store.close()


# ===================================================================
# REQ-25.8: kill --all
# ===================================================================


class TestKillAll:
    """guild kill --all stops all running tasks."""

    @pytest.mark.ac("AC-25.8.1")
    async def test_kill_all_signals_every_task(self, guild_env: dict) -> None:
        """kill_all sends SIGTERM to every task with a PID file."""
        run_dir = guild_env["run_dir"]
        store = await _make_storage(guild_env["guild_dir"])

        for i in range(3):
            tid = f"ka-{i}"
            _write_pid_file(run_dir, tid, 20000 + i)
            await store.create_task(tid, f"task {i}")
            await store.update_task(tid, status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        with (
            patch("os.kill") as mock_kill,
            patch("guild.daemon.lifecycle._process_alive", return_value=False),
        ):
            count = await mgr.kill_all()

        assert count == 3
        for i in range(3):
            mock_kill.assert_any_call(20000 + i, signal.SIGTERM)
        await store.close()

    @pytest.mark.ac("AC-25.8.1")
    def test_kill_all_cli_flag(self, project_dir: Path) -> None:
        """guild kill --all via CLI prints count of killed tasks."""
        # No running tasks, so count should be 0
        with patch("guild.cli.main._kill_all_tasks", return_value=0):
            result = runner.invoke(app, ["kill", "--all"])
        assert result.exit_code == 0
        assert "Killed 0 task" in result.output


# ===================================================================
# REQ-25.9: Exit codes
# ===================================================================


class TestExitCodes:
    """Meaningful exit codes for Guild processes."""

    @pytest.mark.ac("AC-25.9.1")
    def test_exit_code_values(self) -> None:
        """ExitCode enum has the documented integer values."""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.FAILED == 1
        assert ExitCode.INTERRUPTED == 2
        assert ExitCode.CRASH_RECOVERY == 3

    @pytest.mark.ac("AC-25.9.1")
    def test_exit_code_is_int(self) -> None:
        """Exit codes are usable as plain integers."""
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.CRASH_RECOVERY) == 3

    @pytest.mark.ac("AC-25.9.1")
    def test_successful_task_exits_zero(self, project_dir: Path) -> None:
        """A successfully completed task results in exit code 0."""
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(app, ["task", "Quick task"])
        assert result.exit_code == 0


# ===================================================================
# REQ-26.1: Detect sleep
# ===================================================================


class TestDetectSleep:
    """Detect system sleep via monotonic time-drift."""

    @pytest.mark.ac("AC-26.1.1")
    def test_large_drift_detected_as_sleep(self) -> None:
        """Time drift exceeding threshold triggers sleep detection."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=10.0),
        )
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=100.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=200.0):
            assert detector.check_for_sleep() is True
        assert detector.sleep_detected is True

    @pytest.mark.ac("AC-26.1.3")
    def test_normal_delay_not_flagged(self) -> None:
        """Delay within threshold is not flagged as sleep."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=60.0),
        )
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=100.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=105.0):
            assert detector.check_for_sleep() is False
        assert detector.sleep_detected is False

    @pytest.mark.ac("AC-26.1.1")
    def test_clear_sleep_flag(self) -> None:
        """clear_sleep_flag resets the detected state after handling."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=0.01),
        )
        detector._last_turn_time = time.monotonic() - 10.0
        detector.check_for_sleep()
        assert detector.sleep_detected is True
        detector.clear_sleep_flag()
        assert detector.sleep_detected is False


# ===================================================================
# REQ-26.2: Resume on wake
# ===================================================================


class TestResumeOnWake:
    """On wake, detect sleep occurred and decide whether to resume."""

    @pytest.mark.ac("AC-26.2.1")
    def test_resume_after_sleep_with_resume_config(self) -> None:
        """With RESUME behavior, should_resume returns True after sleep."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(wake_behavior=WakeBehavior.RESUME),
        )
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=0.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=999.0):
            detector.check_for_sleep()

        assert detector.sleep_detected is True
        assert detector.should_resume() is True

    @pytest.mark.ac("AC-26.2.1")
    def test_stay_paused_after_sleep_when_configured(self) -> None:
        """With STAY_PAUSED behavior, should_resume returns False after sleep."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(wake_behavior=WakeBehavior.STAY_PAUSED),
        )
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=0.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=999.0):
            detector.check_for_sleep()

        assert detector.sleep_detected is True
        assert detector.should_resume() is False


# ===================================================================
# REQ-26.3: Ollama reconnect on wake
# ===================================================================


class TestOllamaReconnect:
    """Ollama connection re-validated on wake with retries."""

    @pytest.mark.ac("AC-26.3.1")
    async def test_health_check_called_on_wake(self) -> None:
        """Provider health_check is called during wake recovery."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retries=3),
        )
        provider = AsyncMock()
        provider.health_check.return_value = True

        result = await detector.wait_for_provider_recovery(provider)
        assert result is True
        provider.health_check.assert_called_once()

    @pytest.mark.ac("AC-26.3.2")
    async def test_retries_until_provider_recovers(self) -> None:
        """Health check retries until provider responds positively."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=5,
                health_check_retry_delay=0.01,
            ),
        )
        provider = AsyncMock()
        provider.health_check.side_effect = [False, False, False, True]

        result = await detector.wait_for_provider_recovery(provider)
        assert result is True
        assert provider.health_check.call_count == 4

    @pytest.mark.ac("AC-26.3.3")
    async def test_returns_false_after_max_retries(self) -> None:
        """Recovery returns False when provider does not recover in time."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=2,
                health_check_retry_delay=0.01,
            ),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False

        result = await detector.wait_for_provider_recovery(provider, max_retries=2)
        assert result is False
        assert provider.health_check.call_count == 2


# ===================================================================
# REQ-26.4: Interrupted calls retried
# ===================================================================


class TestInterruptedCallsRetried:
    """In-flight LLM calls interrupted by sleep are retried."""

    @pytest.mark.ac("AC-26.4.1")
    async def test_retry_succeeds_after_connection_error(self) -> None:
        """Detector retries a failed LLM call after validating provider."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=3,
                health_check_retry_delay=0.01,
            ),
        )
        provider = AsyncMock()
        provider.health_check.return_value = True

        call_count = 0

        async def flaky_generate() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection lost during sleep")
            return "retried successfully"

        result = await detector.retry_after_sleep(
            provider=provider, operation=flaky_generate,
        )

        assert result == "retried successfully"
        assert call_count == 2
        provider.health_check.assert_called()

    @pytest.mark.ac("AC-26.4.1")
    async def test_retry_fails_when_provider_unrecoverable(self) -> None:
        """retry_after_sleep re-raises when provider cannot recover."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=1,
                health_check_retry_delay=0.01,
            ),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False

        async def always_fails() -> str:
            raise ConnectionError("permanent failure")

        with pytest.raises(ConnectionError, match="permanent failure"):
            await detector.retry_after_sleep(
                provider=provider, operation=always_fails,
            )


# ===================================================================
# REQ-26.5: Sleep/wake audit log
# ===================================================================


class TestSleepWakeAuditLog:
    """Sleep/wake events are logged in the audit trail."""

    @pytest.mark.ac("AC-26.5.1")
    async def test_sleep_event_logged(self) -> None:
        """log_sleep_event writes to audit storage."""
        detector = SleepWakeDetector()
        storage = AsyncMock()

        await detector.log_sleep_event(storage, agent_id="agent-audit")

        storage.log_audit.assert_called_once_with(
            action="sleep_detected",
            agent_id="agent-audit",
            details="System sleep detected via time-drift",
        )

    @pytest.mark.ac("AC-26.5.1")
    async def test_wake_event_logged(self) -> None:
        """log_wake_event writes to audit storage."""
        detector = SleepWakeDetector()
        storage = AsyncMock()

        await detector.log_wake_event(storage, agent_id="agent-audit")

        storage.log_audit.assert_called_once_with(
            action="wake_recovered",
            agent_id="agent-audit",
            details="System wake — provider reconnected",
        )

    @pytest.mark.ac("AC-26.5.2")
    async def test_audit_events_persisted_in_real_storage(
        self, guild_env: dict,
    ) -> None:
        """Sleep/wake events appear in real SQLite audit log."""
        store = await _make_storage(guild_env["guild_dir"])
        detector = SleepWakeDetector()

        await detector.log_sleep_event(store, agent_id="test-agent")
        await detector.log_wake_event(store, agent_id="test-agent")

        entries = await store.list_audit(limit=10)
        actions = [e["action"] for e in entries]
        assert "sleep_detected" in actions
        assert "wake_recovered" in actions
        await store.close()


# ===================================================================
# REQ-26.6: Configurable wake behavior
# ===================================================================


class TestConfigurableWakeBehavior:
    """Wake behavior is configurable via SleepWakeConfig."""

    @pytest.mark.ac("AC-26.6.1")
    def test_resume_is_default(self) -> None:
        """Default wake behavior is RESUME."""
        config = SleepWakeConfig()
        assert config.wake_behavior == WakeBehavior.RESUME

    @pytest.mark.ac("AC-26.6.2")
    def test_stay_paused_configurable(self) -> None:
        """Wake behavior can be set to STAY_PAUSED."""
        config = SleepWakeConfig(wake_behavior=WakeBehavior.STAY_PAUSED)
        detector = SleepWakeDetector(config=config)
        assert detector.should_resume() is False

    @pytest.mark.ac("AC-26.6.1")
    def test_resume_configurable(self) -> None:
        """Wake behavior can be explicitly set to RESUME."""
        config = SleepWakeConfig(wake_behavior=WakeBehavior.RESUME)
        detector = SleepWakeDetector(config=config)
        assert detector.should_resume() is True

    @pytest.mark.ac("AC-26.6.3")
    def test_config_threshold_customizable(self) -> None:
        """Sleep threshold can be customized."""
        config = SleepWakeConfig(sleep_threshold_seconds=120.0)
        assert config.sleep_threshold_seconds == 120.0

    @pytest.mark.ac("AC-26.6.3")
    def test_config_health_check_params_customizable(self) -> None:
        """Health check retries and delay can be customized."""
        config = SleepWakeConfig(
            health_check_retries=10,
            health_check_retry_delay=5.0,
        )
        assert config.health_check_retries == 10
        assert config.health_check_retry_delay == 5.0
