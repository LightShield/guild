"""Entry point for background daemon process.

Launched by `guild task --background` to run an agent loop in a detached process.
Usage: python -m guild.daemon.run <task_id> <guild_dir>
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from guild.config.loader import DB_FILENAME
from guild.task.spec import TaskStatus

__all__: list[str] = []

logger = logging.getLogger(__name__)


async def _run_task(
    task_id: str, guild_dir: Path
) -> None:  # pragma: no cover — daemon subprocess entry point, tested via integration
    """Load config, create provider, wrap in supervisor, and execute."""
    from guild.agent.loop import DEFAULT_MAX_TURNS, AgentLoop
    from guild.agent.prompts import GUILD_MASTER_PROMPT
    from guild.cli.task_runner import create_provider_for_backend
    from guild.config.loader import load_config
    from guild.daemon.supervisor import DaemonSupervisor
    from guild.storage.sqlite import Storage
    from guild.tools.registry import build_tool_executors

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)
    db_path = guild_dir / DB_FILENAME

    # Load task from storage
    async with Storage(db_path) as store:
        task = await store.get_task(task_id)
        if task is None:
            logger.error("Task %s not found in storage", task_id)
            return

        description = task["description"]
        await store.update_task(task_id, status=TaskStatus.RUNNING)

        # Create provider and tools
        provider = create_provider_for_backend(config.provider_name, config.base_url, config.model)
        tool_executors = build_tool_executors()

        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=working_dir,
            max_turns=DEFAULT_MAX_TURNS,
        )

        # Run under supervisor
        run_dir = guild_dir / "run"
        supervisor = DaemonSupervisor(run_dir=run_dir, task_id=task_id)

        try:
            result = await supervisor.run(loop.run(GUILD_MASTER_PROMPT, description))
            await store.update_task(task_id, status=TaskStatus.COMPLETED, result=result)
            await store.log_audit(
                action="task_completed",
                agent_id="guild-daemon",
                details=f"task={task_id}",
            )
        except Exception as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            await store.update_task(task_id, status=TaskStatus.FAILED, result=str(exc))


def main() -> None:  # pragma: no cover — CLI entry point boilerplate
    """CLI entry point for the daemon runner."""
    if len(sys.argv) < 3:
        logger.error("Usage: python -m guild.daemon.run <task_id> <guild_dir>")
        sys.exit(1)

    task_id = sys.argv[1]
    guild_dir = Path(sys.argv[2])

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(_run_task(task_id, guild_dir))


if __name__ == "__main__":
    main()  # pragma: no cover — CLI entry point boilerplate
