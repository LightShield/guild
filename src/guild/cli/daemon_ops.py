"""Daemon and background task operations for the Guild CLI.

Handles launching background tasks, process management (kill, pause,
resume), and PID file tracking.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING

from guild.config.loader import DB_FILENAME

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "create_task_in_storage",
    "get_running_tasks",
    "kill_all_tasks",
    "kill_task",
    "launch_background_task",
    "pause_task",
    "resume_task",
]


def create_task_in_storage(guild_dir: Path, description: str) -> str:
    """Create a task record in storage and return its ID."""
    import uuid

    from guild.storage.sqlite import Storage

    task_id = str(uuid.uuid4())
    db_path = guild_dir / DB_FILENAME

    async def _create() -> None:
        store = Storage(db_path)
        await store.connect()
        await store.create_task(task_id, description)
        await store.close()

    asyncio.run(_create())
    return task_id


def launch_background_task(guild_dir: Path, task_id: str) -> None:
    """Fork a background daemon process to run the task."""
    subprocess.Popen(
        [sys.executable, "-m", "guild.daemon.run", task_id, str(guild_dir)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def get_running_tasks(run_dir: Path) -> list[dict]:
    """List tasks with live PID files in the run directory."""
    import os as _os

    tasks: list[dict] = []
    for pid_file in run_dir.glob("*.pid"):
        try:
            pid = int(pid_file.read_text().strip())
            _os.kill(pid, 0)  # Check if alive
            tasks.append({"task_id": pid_file.stem, "pid": pid})
        except (OSError, ValueError):
            continue
    return tasks


def kill_task(
    task_id: str, guild_dir: Path
) -> bool:  # pragma: no cover — requires running daemon process
    """Kill a task by sending SIGTERM."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / DB_FILENAME

    async def _do_kill() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.kill_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_kill())


def kill_all_tasks(guild_dir: Path) -> int:  # pragma: no cover — requires running daemon process
    """Kill all running tasks."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / DB_FILENAME

    async def _do_kill_all() -> int:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        count = await mgr.kill_all()
        await store.close()
        return count

    return asyncio.run(_do_kill_all())


def pause_task(
    task_id: str, guild_dir: Path
) -> bool:  # pragma: no cover — requires running daemon process
    """Pause a running task."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / DB_FILENAME

    async def _do_pause() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.pause_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_pause())


def resume_task(
    task_id: str, guild_dir: Path
) -> bool:  # pragma: no cover — requires running daemon process
    """Resume a paused task."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / DB_FILENAME

    async def _do_resume() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.resume_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_resume())
