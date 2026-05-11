"""Tests for cli/daemon_ops.py — daemon and background task operations (REQ-06.5)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from guild.cli.daemon_ops import (
    create_task_in_storage,
    get_running_tasks,
    launch_background_task,
)


@pytest.mark.unit
@pytest.mark.req("REQ-23.5")
class TestGetRunningTasks:
    """get_running_tasks reads PID files and checks liveness."""

    def test_returns_empty_for_empty_dir(self, tmp_path: Path) -> None:
        """No PID files means no running tasks."""
        result = get_running_tasks(tmp_path)
        assert result == []

    def test_returns_task_for_live_pid(self, tmp_path: Path) -> None:
        """A PID file whose process is alive yields a task entry."""
        pid = os.getpid()  # Current process is definitely alive
        pid_file = tmp_path / "task-abc.pid"
        pid_file.write_text(str(pid))

        result = get_running_tasks(tmp_path)
        assert len(result) == 1
        assert result[0]["task_id"] == "task-abc"
        assert result[0]["pid"] == pid

    def test_skips_dead_pid(self, tmp_path: Path) -> None:
        """A PID file referencing a non-existent process is skipped."""
        pid_file = tmp_path / "dead-task.pid"
        pid_file.write_text("999999999")  # Almost certainly not running

        result = get_running_tasks(tmp_path)
        assert result == []

    def test_skips_malformed_pid_file(self, tmp_path: Path) -> None:
        """A PID file with non-numeric content is skipped."""
        pid_file = tmp_path / "bad-task.pid"
        pid_file.write_text("not-a-number")

        result = get_running_tasks(tmp_path)
        assert result == []

    def test_multiple_tasks_mixed_liveness(self, tmp_path: Path) -> None:
        """Only live PIDs are returned from a mix of live and dead."""
        live_pid = os.getpid()
        (tmp_path / "live.pid").write_text(str(live_pid))
        (tmp_path / "dead.pid").write_text("999999999")

        result = get_running_tasks(tmp_path)
        assert len(result) == 1
        assert result[0]["task_id"] == "live"


@pytest.mark.unit
@pytest.mark.req("REQ-23.1")
class TestLaunchBackgroundTask:
    """launch_background_task forks a subprocess."""

    @patch("guild.cli.daemon_ops.subprocess.Popen")
    def test_popen_called_with_correct_args(self, mock_popen: MagicMock) -> None:
        """subprocess.Popen is called with the daemon module and task ID."""
        guild_dir = Path("/fake/.guild")
        launch_background_task(guild_dir, "task-123")

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "guild.daemon.run" in cmd[2]
        assert "task-123" in cmd
        assert str(guild_dir) in cmd
        assert call_args[1]["start_new_session"] is True


@pytest.mark.unit
@pytest.mark.req("REQ-23.2")
class TestCreateTaskInStorage:
    """create_task_in_storage creates a task record and returns an ID."""

    @patch("guild.cli.daemon_ops.asyncio.run")
    def test_returns_uuid_string(self, mock_run: MagicMock) -> None:
        """create_task_in_storage returns a UUID string."""
        guild_dir = Path("/fake/.guild")
        result = create_task_in_storage(guild_dir, "test task")
        assert isinstance(result, str)
        assert len(result) > 0
        mock_run.assert_called_once()
