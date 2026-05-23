"""Entry point for background team task execution.

Usage: python -m guild.daemon.team_run <task_id> <guild_dir> <team_name>
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from logger_python import get_logger

from guild.config.loader import DB_FILENAME
from guild.task.spec import TaskStatus

__all__: list[str] = []

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


async def _run_team_task(task_id: str, guild_dir: Path, team_name: str) -> None:
    """Load an existing task and execute it through a saved team."""
    from guild.cli.task_runner import run_team_task
    from guild.config.loader import load_config
    from guild.daemon.supervisor import DaemonSupervisor
    from guild.storage.sqlite import Storage

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)
    db_path = guild_dir / DB_FILENAME

    async with Storage(db_path) as store:
        task = await store.get_task(task_id)
        if task is None:
            logger.info("Task %s not found in storage", task_id)
            return
        description = task["description"]
        await store.update_task(
            task_id,
            status=TaskStatus.RUNNING,
            assigned_agent=team_name,
            result=f"Starting flow '{team_name}'...",
        )
        await store.add_task_event(
            task_id,
            "running",
            f"Daemon started flow '{team_name}'; loading blocks and connections.",
        )
        await store.log_audit(
            action="team_task_started",
            agent_id=team_name,
            details=f"task={task_id} team={team_name}",
        )

    run_dir = guild_dir / "run"
    supervisor = DaemonSupervisor(run_dir=run_dir, task_id=task_id)

    try:
        result = await supervisor.run(
            run_team_task(
                config,
                working_dir,
                guild_dir,
                team_name,
                description,
                parent_task_id=task_id,
            )
        )
        async with Storage(db_path) as store:
            await store.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=_now(),
            )
            await store.add_task_event(
                task_id,
                "completed",
                f"Flow '{team_name}' completed.",
            )
            await store.log_audit(
                action="team_task_completed",
                agent_id=team_name,
                details=f"task={task_id} team={team_name}",
            )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("Team task %s failed: %s", task_id, exc)
        async with Storage(db_path) as store:
            await store.update_task(
                task_id,
                status=TaskStatus.FAILED,
                result=str(exc),
                completed_at=_now(),
            )
            await store.add_task_event(
                task_id,
                "failed",
                f"Flow '{team_name}' failed: {exc}",
            )


def main() -> None:  # pragma: no cover - CLI entry point boilerplate
    """CLI entry point for the team daemon runner."""
    if len(sys.argv) < 4:
        logger.error("Usage: python -m guild.daemon.team_run <task_id> <guild_dir> <team_name>")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(_run_team_task(sys.argv[1], Path(sys.argv[2]), sys.argv[3]))


if __name__ == "__main__":
    main()
