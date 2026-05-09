"""Tests for daemon/lifecycle.py — process lifecycle management (REQ-25)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from guild.daemon.lifecycle import ExitCode, LifecycleManager
from guild.storage.sqlite import Storage


async def _make_storage(tmp_path: Path) -> Storage:
    """Create an in-memory-style storage in tmp_path for testing."""
    db_path = tmp_path / "guild.db"
    storage = Storage(db_path)
    await storage.connect()
    return storage


def _write_pid_file(run_dir: Path, task_id: str, pid: int) -> Path:
    """Write a fake PID file for a task."""
    pid_file = run_dir / f"{task_id}.pid"
    pid_file.write_text(str(pid))
    return pid_file


def _write_sock_file(run_dir: Path, name: str) -> Path:
    """Write a fake socket file."""
    sock_file = run_dir / f"{name}.sock"
    sock_file.write_text("")
    return sock_file


# ------------------------------------------------------------------
# REQ-25.1: guild kill <task_id>
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.1")
class TestKillTask:
    """Kill sends SIGTERM, waits, escalates to SIGKILL."""

    async def test_kill_sends_sigterm_to_pid(self, tmp_path: Path) -> None:
        """kill_task sends SIGTERM to the process identified by PID file."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "task-1", 12345)
        await storage.create_task("task-1", "test task")
        await storage.update_task("task-1", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        with (
            patch("os.kill") as mock_kill,
            patch("guild.daemon.lifecycle._process_alive", return_value=False),
        ):
            result = await mgr.kill_task("task-1")

        assert result is True
        # First call should be SIGTERM
        mock_kill.assert_any_call(12345, 15)  # signal.SIGTERM == 15
        await storage.close()

    async def test_kill_waits_for_graceful_then_sigkill(self, tmp_path: Path) -> None:
        """If process survives SIGTERM, SIGKILL is sent after timeout."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "task-2", 99999)
        await storage.create_task("task-2", "stubborn task")
        await storage.update_task("task-2", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        # Process stays alive after SIGTERM
        with (
            patch("os.kill") as mock_kill,
            patch(
                "guild.daemon.lifecycle._process_alive",
                return_value=True,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await mgr.kill_task("task-2", timeout=0.01)

        assert result is True
        # Should have sent SIGKILL (9)
        mock_kill.assert_any_call(99999, 9)
        await storage.close()

    async def test_kill_returns_error_for_nonexistent_task(self, tmp_path: Path) -> None:
        """kill_task returns False when no PID file exists for task."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)
        result = await mgr.kill_task("nonexistent-task")

        assert result is False
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.2: guild pause <task_id>
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.2")
class TestPauseTask:
    """Pause writes status to DB."""

    async def test_pause_writes_paused_status_to_db(self, tmp_path: Path) -> None:
        """pause_task updates task status to 'paused' in storage."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        await storage.create_task("task-p1", "pausable")
        await storage.update_task("task-p1", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)
        result = await mgr.pause_task("task-p1")

        assert result is True
        task = await storage.get_task("task-p1")
        assert task is not None
        assert task["status"] == "paused"
        await storage.close()

    async def test_pause_returns_error_if_not_running(self, tmp_path: Path) -> None:
        """pause_task returns False if task is not in 'running' status."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        await storage.create_task("task-p2", "pending task")
        # status stays 'pending' (default)

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)
        result = await mgr.pause_task("task-p2")

        assert result is False
        # Status should remain unchanged
        task = await storage.get_task("task-p2")
        assert task is not None
        assert task["status"] == "pending"
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.3: guild resume <task_id>
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.3")
class TestResumeTask:
    """Resume changes status from paused to running."""

    async def test_resume_changes_status_from_paused_to_running(self, tmp_path: Path) -> None:
        """resume_task changes task status from 'paused' to 'running'."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        await storage.create_task("task-r1", "resumable")
        await storage.update_task("task-r1", status="paused")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)
        result = await mgr.resume_task("task-r1")

        assert result is True
        task = await storage.get_task("task-r1")
        assert task is not None
        assert task["status"] == "running"
        await storage.close()

    async def test_resume_returns_error_if_not_paused(self, tmp_path: Path) -> None:
        """resume_task returns False if task is not in 'paused' status."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        await storage.create_task("task-r2", "running task")
        await storage.update_task("task-r2", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)
        result = await mgr.resume_task("task-r2")

        assert result is False
        task = await storage.get_task("task-r2")
        assert task is not None
        assert task["status"] == "running"
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.5: Crash recovery — detect orphaned PID files
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.5")
class TestOrphanDetection:
    """Detect PID files for processes no longer alive."""

    async def test_detect_orphaned_pid_files(self, tmp_path: Path) -> None:
        """detect_orphans returns task IDs whose PID processes are dead."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "dead-task", 11111)
        _write_pid_file(run_dir, "also-dead", 22222)

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        # Both PIDs are dead
        with patch("guild.daemon.lifecycle._process_alive", return_value=False):
            orphans = mgr.detect_orphans()

        assert set(orphans) == {"dead-task", "also-dead"}
        await storage.close()

    async def test_orphan_detection_skips_live_processes(self, tmp_path: Path) -> None:
        """detect_orphans does NOT report tasks whose processes are alive."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "live-task", 33333)
        _write_pid_file(run_dir, "dead-task", 44444)

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        def selective_alive(pid: int) -> bool:
            return pid == 33333

        with patch(
            "guild.daemon.lifecycle._process_alive",
            side_effect=selective_alive,
        ):
            orphans = mgr.detect_orphans()

        assert orphans == ["dead-task"]
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.7: Stale lock detection
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.7")
class TestStaleLockCleanup:
    """Dead socket files are cleaned up automatically."""

    async def test_stale_socket_cleaned_on_startup(self, tmp_path: Path) -> None:
        """cleanup_stale_locks removes .sock and .pid files for dead procs."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "stale-task", 55555)
        _write_sock_file(run_dir, "stale-task")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        with patch("guild.daemon.lifecycle._process_alive", return_value=False):
            count = mgr.cleanup_stale_locks()

        assert count == 1
        assert not (run_dir / "stale-task.pid").exists()
        assert not (run_dir / "stale-task.sock").exists()
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.8: guild kill --all
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.8")
class TestKillAll:
    """Kill all running tasks."""

    async def test_kill_all_stops_multiple_tasks(self, tmp_path: Path) -> None:
        """kill_all kills all tasks with PID files and returns count."""
        storage = await _make_storage(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _write_pid_file(run_dir, "t1", 10001)
        _write_pid_file(run_dir, "t2", 10002)
        _write_pid_file(run_dir, "t3", 10003)
        await storage.create_task("t1", "task 1")
        await storage.update_task("t1", status="running")
        await storage.create_task("t2", "task 2")
        await storage.update_task("t2", status="running")
        await storage.create_task("t3", "task 3")
        await storage.update_task("t3", status="running")

        mgr = LifecycleManager(run_dir=run_dir, storage=storage)

        with (
            patch("os.kill") as mock_kill,
            patch(
                "guild.daemon.lifecycle._process_alive",
                return_value=False,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await mgr.kill_all()

        assert count == 3
        # SIGTERM sent to each PID
        for pid in (10001, 10002, 10003):
            mock_kill.assert_any_call(pid, 15)
        await storage.close()


# ------------------------------------------------------------------
# REQ-25.9: Meaningful exit codes
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-25.9")
class TestExitCodes:
    """Verify exit code enum values."""

    def test_exit_code_success(self) -> None:
        """ExitCode.SUCCESS is 0."""
        assert ExitCode.SUCCESS == 0

    def test_exit_code_failed(self) -> None:
        """ExitCode.FAILED is 1."""
        assert ExitCode.FAILED == 1

    def test_exit_code_interrupted(self) -> None:
        """ExitCode.INTERRUPTED is 2."""
        assert ExitCode.INTERRUPTED == 2

    def test_exit_code_crash_recovery(self) -> None:
        """ExitCode.CRASH_RECOVERY is 3."""
        assert ExitCode.CRASH_RECOVERY == 3


# ------------------------------------------------------------------
# REQ-23.7: Multiple concurrent background tasks
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-23.7")
class TestTaskQueue:
    """TaskQueue manages concurrent background task execution."""

    async def test_task_queue_enqueue_dequeue(self, tmp_path: Path) -> None:
        """enqueue adds task, dequeue retrieves it."""
        from guild.daemon.lifecycle import TaskQueue

        storage = await _make_storage(tmp_path)
        queue = TaskQueue(max_concurrent=2, storage=storage)

        position = await queue.enqueue("task-1")
        assert position == 0

        position = await queue.enqueue("task-2")
        assert position == 1

        task_id = await queue.dequeue()
        assert task_id == "task-1"

        task_id = await queue.dequeue()
        assert task_id == "task-2"

        task_id = await queue.dequeue()
        assert task_id is None

        await storage.close()

    async def test_queue_respects_max_concurrent(self, tmp_path: Path) -> None:
        """dequeue returns None when max_concurrent active tasks reached."""
        from guild.daemon.lifecycle import TaskQueue

        storage = await _make_storage(tmp_path)
        queue = TaskQueue(max_concurrent=1, storage=storage)

        await queue.enqueue("task-a")
        await queue.enqueue("task-b")

        # Dequeue first — active_count goes to 1
        task_id = await queue.dequeue()
        assert task_id == "task-a"
        assert queue.active_count == 1

        # Second dequeue should return None (at max)
        task_id = await queue.dequeue()
        assert task_id is None

        await storage.close()

    async def test_queue_state_persisted(self, tmp_path: Path) -> None:
        """get_queue_state returns the current queue contents."""
        from guild.daemon.lifecycle import TaskQueue

        storage = await _make_storage(tmp_path)
        queue = TaskQueue(max_concurrent=3, storage=storage)

        await queue.enqueue("t1")
        await queue.enqueue("t2")
        await queue.enqueue("t3")

        state = await queue.get_queue_state()
        assert len(state) == 3
        assert state[0]["task_id"] == "t1"
        assert state[1]["task_id"] == "t2"
        assert state[2]["task_id"] == "t3"

        await storage.close()
