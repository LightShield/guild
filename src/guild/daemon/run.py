"""Entry point for background daemon process.

Launched by `guild task --background` to run an agent loop in a detached process.
Usage: python -m guild.daemon.run <task_id> <guild_dir>
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

__all__: list[str] = []

logger = logging.getLogger(__name__)


async def _run_task(task_id: str, guild_dir: Path) -> None:  # pragma: no cover — daemon subprocess entry point, tested via integration
    """Load config, create provider, wrap in supervisor, and execute."""
    from guild.agent.loop import AgentLoop
    from guild.config.loader import load_config
    from guild.daemon.supervisor import DaemonSupervisor
    from guild.provider.ollama import create_provider
    from guild.storage.sqlite import Storage
    from guild.tools.file_ops import execute_file_read, execute_file_write
    from guild.tools.search import execute_glob, execute_search
    from guild.tools.shell import execute_shell

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)
    db_path = guild_dir / "guild.db"

    # Load task from storage
    store = Storage(db_path)
    await store.connect()

    task = await store.get_task(task_id)
    if task is None:
        logger.error("Task %s not found in storage", task_id)
        await store.close()
        return

    description = task["description"]
    await store.update_task(task_id, status="running")

    # Create provider and tools
    provider = create_provider(config.base_url, config.model)
    tool_executors = {
        "file_read": execute_file_read,
        "file_write": execute_file_write,
        "shell": execute_shell,
        "search": execute_search,
        "glob": execute_glob,
    }

    system_prompt = (
        "You are an autonomous coding agent. Complete the task described below. "
        "Use the available tools to read files, write files, search code, and "
        "run shell commands. When done, provide a brief summary of what you "
        "accomplished."
    )

    loop = AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=50,
    )

    # Run under supervisor
    run_dir = guild_dir / "run"
    supervisor = DaemonSupervisor(run_dir=run_dir, task_id=task_id)

    try:
        result = await supervisor.run(loop.run(system_prompt, description))
        await store.update_task(task_id, status="completed", result=result)
        await store.log_audit(
            action="task_completed",
            agent_id="guild-daemon",
            details=f"task={task_id}",
        )
    except Exception as exc:
        logger.error("Task %s failed: %s", task_id, exc)
        await store.update_task(task_id, status="failed", result=str(exc))
    finally:
        await store.close()


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
