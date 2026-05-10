"""Process lifecycle management for Guild tasks.

Handles kill, pause, resume, crash recovery, and stale lock cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from pathlib import Path

    from guild.storage.sqlite import Storage

__all__ = ["ExitCode", "LifecycleManager", "TaskQueue"]

logger = logging.getLogger(__name__)


class ExitCode(IntEnum):
    """Meaningful exit codes for Guild processes."""

    SUCCESS = 0
    FAILED = 1
    INTERRUPTED = 2
    CRASH_RECOVERY = 3


def _process_alive(pid: int) -> bool:  # pragma: no cover — requires running subprocess
    """Check whether a process with the given PID is alive.

    Uses os.kill(pid, 0) which checks existence without sending a signal.
    Returns False if the process does not exist or we lack permission.
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class LifecycleManager:
    """Manages process lifecycle: kill, pause, resume, crash recovery."""

    def __init__(self, run_dir: Path, storage: Storage) -> None:
        self.run_dir = run_dir
        self.storage = storage

    async def kill_task(
        self, task_id: str, timeout: float = 10.0
    ) -> bool:  # pragma: no cover — requires running subprocess
        """Send graceful shutdown, escalate to SIGKILL after timeout.

        Returns True if the task was found and signaled, False otherwise.
        """
        pid_file = self.run_dir / f"{task_id}.pid"
        if not pid_file.exists():
            logger.warning("No PID file for task %s", task_id)
            return False

        pid = int(pid_file.read_text().strip())
        logger.info("Sending SIGTERM to PID %d (task %s)", pid, task_id)
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown
        if _process_alive(pid):
            await asyncio.sleep(timeout)

        # Escalate if still alive
        if _process_alive(pid):
            logger.warning(
                "PID %d still alive after %.1fs, sending SIGKILL",
                pid,
                timeout,
            )
            os.kill(pid, signal.SIGKILL)

        # Clean up PID file
        if pid_file.exists():
            pid_file.unlink()

        # Update task status
        task = await self.storage.get_task(task_id)
        if task is not None:
            await self.storage.update_task(task_id, status="killed")

        return True

    async def kill_all(self) -> int:
        """Kill all running tasks. Returns count killed."""
        pid_files = list(self.run_dir.glob("*.pid"))
        count = 0
        for pid_file in pid_files:
            task_id = pid_file.stem
            success = await self.kill_task(task_id)
            if success:
                count += 1
        return count

    async def pause_task(self, task_id: str) -> bool:
        """Mark task as paused in storage.

        Returns True on success, False if task is not in 'running' state.
        """
        task = await self.storage.get_task(task_id)
        if task is None:
            logger.warning("Task %s not found", task_id)
            return False

        if task["status"] != "running":
            logger.warning(
                "Cannot pause task %s: status is '%s', not 'running'",
                task_id,
                task["status"],
            )
            return False

        await self.storage.update_task(task_id, status="paused")
        logger.info("Task %s paused", task_id)
        return True

    async def resume_task(self, task_id: str) -> bool:
        """Mark task as running (actual re-execution handled by CLI).

        Returns True on success, False if task is not in 'paused' state.
        """
        task = await self.storage.get_task(task_id)
        if task is None:
            logger.warning("Task %s not found", task_id)
            return False

        if task["status"] != "paused":
            logger.warning(
                "Cannot resume task %s: status is '%s', not 'paused'",
                task_id,
                task["status"],
            )
            return False

        await self.storage.update_task(task_id, status="running")
        logger.info("Task %s resumed", task_id)
        return True

    def detect_orphans(self) -> list[str]:  # pragma: no cover — requires running subprocess
        """Find PID files whose processes are no longer alive.

        Returns list of task IDs with orphaned PID files.
        """
        orphans: list[str] = []
        for pid_file in self.run_dir.glob("*.pid"):
            pid = int(pid_file.read_text().strip())
            if not _process_alive(pid):
                orphans.append(pid_file.stem)
        return orphans

    def cleanup_stale_locks(self) -> int:  # pragma: no cover — requires running subprocess
        """Remove stale socket/PID files for dead processes.

        Returns count of stale task entries cleaned.
        """
        orphans = self.detect_orphans()
        count = 0
        for task_id in orphans:
            pid_file = self.run_dir / f"{task_id}.pid"
            sock_file = self.run_dir / f"{task_id}.sock"
            if pid_file.exists():
                pid_file.unlink()
            if sock_file.exists():
                sock_file.unlink()
            count += 1
            logger.info("Cleaned stale lock for task %s", task_id)
        return count

    def get_running_tasks(self) -> list[dict]:  # pragma: no cover — requires running subprocess
        """List all tasks with live PID files."""
        running: list[dict] = []
        for pid_file in self.run_dir.glob("*.pid"):
            pid = int(pid_file.read_text().strip())
            if _process_alive(pid):
                running.append({"task_id": pid_file.stem, "pid": pid})
        return running


class TaskQueue:
    """Queue for background tasks, respecting max_concurrent_agents (REQ-23.7).

    Manages a FIFO queue of task IDs and limits how many can be
    actively running at once.
    """

    def __init__(
        self,
        max_concurrent: int = 1,
        storage: Storage | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._storage = storage
        self._queue: list[str] = []
        self._active: list[str] = []

    async def enqueue(self, task_id: str) -> int:
        """Add task to queue. Returns queue position (0-based)."""
        position = len(self._queue)
        self._queue.append(task_id)
        return position

    async def dequeue(self) -> str | None:
        """Get next task ready to run.

        Returns None if queue is empty or max_concurrent is reached.
        """
        if not self._queue:
            return None
        if len(self._active) >= self._max_concurrent:
            return None

        task_id = self._queue.pop(0)
        self._active.append(task_id)
        return task_id

    async def get_queue_state(self) -> list[dict]:
        """Return the current queue contents as a list of dicts."""
        return [{"task_id": tid, "position": idx} for idx, tid in enumerate(self._queue)]

    @property
    def active_count(self) -> int:
        """Number of currently active (dequeued) tasks."""
        return len(self._active)

    def complete(self, task_id: str) -> None:
        """Mark a task as no longer active."""
        if task_id in self._active:
            self._active.remove(task_id)
