"""Guild CLI — Typer-based command-line interface (REQ-05.1, REQ-05.2).

Primary entry point for all Guild operations: init, task, chat, status,
config, and audit commands.
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).
# Note: do NOT use `from __future__ import annotations` — Typer 0.9
# requires runtime type annotation introspection.

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from guild import __version__
from guild.config.loader import find_guild_dir, load_config
from guild.provider.ollama import create_provider

__all__ = ["app"]

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="guild",
    help="Guild — autonomous coding agent harness.",
    no_args_is_help=True,
)

_GUILD_MASTER_PROMPT = (
    "You are an autonomous coding agent. Complete the task described below. "
    "Use the available tools to read files, write files, search code, and "
    "run shell commands. When done, provide a brief summary of what you "
    "accomplished."
)

_DEFAULT_CONFIG_TOML = """\
[provider]
provider_name = "ollama"
base_url = "http://localhost:11434"
model = "gemma4-4b-dense-med"
temperature = 0.7
max_tokens = 4096

[guild]
default_permission = "autopilot"
max_concurrent_agents = 1
"""


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    """Guild — autonomous coding agent harness."""
    if version:
        console.print(f"guild {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def init(
    path: Path = typer.Argument(
        default=None,
        help="Directory to initialize (default: current directory).",
    ),
) -> None:
    """Initialize a new Guild project (.guild/ directory)."""
    target = (path or Path.cwd()).resolve()

    guild_dir = target / ".guild"
    if guild_dir.exists():
        console.print(f"[yellow]Already initialized:[/yellow] {guild_dir}")
        raise typer.Exit()

    guild_dir.mkdir(parents=True)

    # Write default config
    config_path = guild_dir / "config.toml"
    config_path.write_text(_DEFAULT_CONFIG_TOML)

    # Create the database
    db_path = guild_dir / "guild.db"
    _init_database(db_path)

    console.print(f"[green]Initialized guild project:[/green] {guild_dir}")


@app.command()
def status() -> None:
    """Show project status — path, task count, agent count."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    project_path = guild_dir.parent
    config = load_config(guild_dir)

    # Get counts from the database
    db_path = guild_dir / "guild.db"
    task_count, agent_count = _get_counts(db_path)

    console.print(f"[bold]Project:[/bold] {project_path}")
    console.print(f"[bold]Provider:[/bold] {config.provider_name}")
    console.print(f"[bold]Model:[/bold] {config.model}")
    console.print(f"[bold]Tasks:[/bold] {task_count}")
    console.print(f"[bold]Agents:[/bold] {agent_count}")


@app.command()
def task(
    description: str = typer.Argument(..., help="Task description."),
    permission: str = typer.Option("autopilot", "--permission", "-p", help="Permission tier."),
    timeout: int = typer.Option(
        0, "--timeout", "-t", help="Autonomy timeout in seconds (0=unlimited)."
    ),
    background: bool = typer.Option(
        False, "--background", "-b", help="Run task in background daemon process."
    ),
) -> None:
    """Run a task using the agent loop."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    if background:
        task_id = _create_task_in_storage(guild_dir, description)
        _launch_background_task(guild_dir, task_id)
        console.print(f"[green]Launched background task:[/green] {task_id}")
        return

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)

    result = asyncio.run(
        _run_task(config, working_dir, description, permission, timeout, guild_dir)
    )
    console.print(f"\n[green]Done.[/green] {result}")


@app.command()
def chat(
    permission: str = typer.Option("ask", "--permission", "-p", help="Permission tier."),
) -> None:
    """Interactive chat with the agent."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    console.print("[bold]Guild interactive chat[/bold] (Ctrl+C to exit)")
    console.print(f"Permission tier: {permission}\n")

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)

    try:
        while True:
            user_input = console.input("[bold blue]> [/bold blue]")
            if not user_input.strip():
                continue

            result = asyncio.run(
                _run_task(config, working_dir, user_input, permission, 0, guild_dir)
            )
            console.print(f"\n{result}\n")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Goodbye.[/dim]")


@app.command(name="config")
def config_cmd(
    set_value: Optional[str] = typer.Option(
        None, "--set", help="Set a config value (e.g. provider.model=llama3)."
    ),
) -> None:
    """Show or modify project configuration."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    config_path = guild_dir / "config.toml"

    if set_value is not None:
        _set_config_value(config_path, set_value)
        console.print(f"[green]Updated:[/green] {set_value}")
        return

    # Show current config
    config = load_config(guild_dir)
    table = Table(title="Guild Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("provider.name", config.provider_name)
    table.add_row("provider.base_url", config.base_url)
    table.add_row("provider.model", config.model)
    table.add_row("provider.temperature", str(config.temperature))
    table.add_row("provider.max_tokens", str(config.max_tokens))
    table.add_row("guild.default_permission", config.default_permission.value)
    table.add_row("guild.max_concurrent_agents", str(config.max_concurrent_agents))

    console.print(table)


@app.command()
def audit(
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries."),
) -> None:
    """Show recent audit log entries."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / "guild.db"
    entries = asyncio.run(_fetch_audit(db_path, limit))

    if not entries:
        console.print("[dim]No audit entries found.[/dim]")
        return

    table = Table(title="Audit Log")
    table.add_column("Timestamp", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Action", style="yellow")
    table.add_column("Details", style="white")

    for entry in entries:
        table.add_row(
            entry.get("timestamp", ""),
            entry.get("agent_id", "") or "-",
            entry.get("action", ""),
            entry.get("details", "") or "",
        )

    console.print(table)


@app.command(name="ps")
def ps_cmd() -> None:
    """Show running/paused Guild tasks."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    run_dir = guild_dir / "run"
    if not run_dir.exists():
        console.print("[dim]No running tasks.[/dim]")
        return

    tasks = _get_running_tasks(run_dir)

    if not tasks:
        console.print("[dim]No running tasks.[/dim]")
        return

    table = Table(title="Guild Tasks")
    table.add_column("Task ID", style="cyan")
    table.add_column("PID", style="yellow")
    table.add_column("Status", style="green")

    for t in tasks:
        table.add_row(t["task_id"], str(t["pid"]), "running")

    console.print(table)


@app.command()
def kill(
    task_id: Optional[str] = typer.Argument(None, help="Task ID to kill."),
    all_tasks: bool = typer.Option(False, "--all", help="Kill all running tasks."),
) -> None:
    """Stop a running task (or all tasks with --all)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    if all_tasks:
        count = _kill_all_tasks(guild_dir)
        console.print(f"[green]Killed {count} task(s).[/green]")
        return

    if task_id is None:
        console.print("[red]Error:[/red] Provide a task ID or use --all.")
        raise typer.Exit(code=1)

    success = _kill_task(task_id, guild_dir)
    if success:
        console.print(f"[green]Killed task:[/green] {task_id}")
    else:
        console.print(f"[yellow]Task not found or not running:[/yellow] {task_id}")


@app.command()
def pause(
    task_id: str = typer.Argument(..., help="Task ID to pause."),
) -> None:
    """Pause a running task."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    success = _pause_task(task_id, guild_dir)
    if success:
        console.print(f"[green]Paused task:[/green] {task_id}")
    else:
        console.print(f"[yellow]Cannot pause task:[/yellow] {task_id}")


@app.command()
def resume(
    task_id: str = typer.Argument(..., help="Task ID to resume."),
) -> None:
    """Resume a paused task."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    success = _resume_task(task_id, guild_dir)
    if success:
        console.print(f"[green]Resumed task:[/green] {task_id}")
    else:
        console.print(f"[yellow]Cannot resume task:[/yellow] {task_id}")


@app.command()
def logs(
    task_id: str = typer.Argument(..., help="Task ID to show logs for."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
) -> None:
    """Stream task output."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    messages = asyncio.run(_fetch_task_messages(guild_dir, task_id))
    if not messages:
        console.print(f"[dim]No messages for task {task_id}.[/dim]")
        return

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        console.print(f"[bold]{role}:[/bold] {content}")


@app.command()
def attach(
    task_id: str = typer.Argument(..., help="Task ID to attach to."),
) -> None:
    """Attach to a running task (interactive)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    # For now, attach behaves like logs --follow
    messages = asyncio.run(_fetch_task_messages(guild_dir, task_id))
    if not messages:
        console.print(f"[dim]No messages for task {task_id}.[/dim]")
        return

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        console.print(f"[bold]{role}:[/bold] {content}")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _init_database(db_path: Path) -> None:
    """Create the SQLite database with schema."""
    from guild.storage.sqlite import Storage

    async def _create():
        store = Storage(db_path)
        await store.connect()
        await store.close()

    asyncio.run(_create())


def _get_counts(db_path: Path) -> tuple[int, int]:
    """Get task and agent counts from the database."""
    from guild.storage.sqlite import Storage

    async def _query():
        store = Storage(db_path)
        await store.connect()
        tasks = await store.list_tasks()
        agents = await store.list_agents()
        await store.close()
        return len(tasks), len(agents)

    if not db_path.exists():
        return 0, 0

    return asyncio.run(_query())


async def _run_task(
    config,
    working_dir: str,
    description: str,
    permission: str,
    timeout: int,
    guild_dir: Path,
) -> str:
    """Execute a task through the agent loop."""
    import uuid

    from guild.agent.loop import AgentLoop
    from guild.permissions.checker import PermissionChecker, PermissionTier
    from guild.storage.sqlite import Storage
    from guild.tools.file_ops import execute_file_read, execute_file_write
    from guild.tools.search import execute_glob, execute_search
    from guild.tools.shell import execute_shell

    # Create provider
    provider = create_provider(config.base_url, config.model)

    # Build tool executors
    tool_executors = {
        "file_read": execute_file_read,
        "file_write": execute_file_write,
        "shell": execute_shell,
        "search": execute_search,
        "glob": execute_glob,
    }

    # Permission checker
    tier = PermissionTier(permission)
    _checker = PermissionChecker(tier=tier)

    # Determine max_turns from timeout (rough: 1 turn ~ 10s)
    max_turns = 50
    if timeout > 0:
        max_turns = min(max(timeout // 10, 5), 200)

    # Create and run agent loop
    loop = AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=max_turns,
    )

    result = await loop.run(_GUILD_MASTER_PROMPT, description)

    # Store task result
    db_path = guild_dir / "guild.db"
    store = Storage(db_path)
    await store.connect()

    task_id = str(uuid.uuid4())
    await store.create_task(task_id, description)
    await store.update_task(task_id, status="completed", result=result)
    await store.log_audit(
        action="task_completed",
        agent_id="guild-master",
        details=f"task={task_id}",
    )
    await store.close()

    return result


async def _fetch_audit(db_path: Path, limit: int) -> list[dict]:
    """Fetch audit log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_audit(limit=limit)
    await store.close()
    return entries


def _load_toml(path: Path) -> dict:
    """Load a TOML file, returning empty dict on failure or missing."""
    import tomllib

    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _set_config_value(config_path: Path, key_value: str) -> None:
    """Set a dotted key=value in a TOML config file.

    Supports dotted keys like 'provider.model=llama3'.
    """
    if "=" not in key_value:
        console.print("[red]Error:[/red] Use format key=value")
        raise typer.Exit(code=1)

    key, value = key_value.split("=", 1)
    parts = key.strip().split(".")

    # Load existing TOML data
    existing = _load_toml(config_path)

    # Navigate to the right nested level
    current = existing
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    # Set the value (try to preserve type)
    current[parts[-1]] = _parse_value(value.strip())

    # Write back as TOML
    _write_toml(config_path, existing)


def _parse_value(value: str) -> str | int | float | bool:
    """Parse a string value into its likely Python type."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _write_toml(path: Path, data: dict) -> None:
    """Write a dict to a TOML file (simple implementation)."""
    lines: list[str] = []
    # Separate top-level scalars from tables
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")

    for section, values in tables.items():
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {_toml_value(v)}")

    lines.append("")  # trailing newline
    path.write_text("\n".join(lines))


def _toml_value(value) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


# ------------------------------------------------------------------
# Daemon / background helpers
# ------------------------------------------------------------------


def _create_task_in_storage(guild_dir: Path, description: str) -> str:
    """Create a task record in storage and return its ID."""
    import uuid

    from guild.storage.sqlite import Storage

    task_id = str(uuid.uuid4())
    db_path = guild_dir / "guild.db"

    async def _create() -> None:
        store = Storage(db_path)
        await store.connect()
        await store.create_task(task_id, description)
        await store.close()

    asyncio.run(_create())
    return task_id


def _launch_background_task(guild_dir: Path, task_id: str) -> None:
    """Fork a background daemon process to run the task."""
    subprocess.Popen(
        [sys.executable, "-m", "guild.daemon.run", task_id, str(guild_dir)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _get_running_tasks(run_dir: Path) -> list[dict]:
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


def _kill_task(task_id: str, guild_dir: Path) -> bool:
    """Kill a task by sending SIGTERM."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / "guild.db"

    async def _do_kill() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.kill_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_kill())


def _kill_all_tasks(guild_dir: Path) -> int:
    """Kill all running tasks."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / "guild.db"

    async def _do_kill_all() -> int:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        count = await mgr.kill_all()
        await store.close()
        return count

    return asyncio.run(_do_kill_all())


def _pause_task(task_id: str, guild_dir: Path) -> bool:
    """Pause a running task."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / "guild.db"

    async def _do_pause() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.pause_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_pause())


def _resume_task(task_id: str, guild_dir: Path) -> bool:
    """Resume a paused task."""
    from guild.daemon.lifecycle import LifecycleManager
    from guild.storage.sqlite import Storage

    run_dir = guild_dir / "run"
    db_path = guild_dir / "guild.db"

    async def _do_resume() -> bool:
        store = Storage(db_path)
        await store.connect()
        mgr = LifecycleManager(run_dir, store)
        result = await mgr.resume_task(task_id)
        await store.close()
        return result

    return asyncio.run(_do_resume())


async def _fetch_task_messages(guild_dir: Path, task_id: str) -> list[dict]:
    """Fetch messages associated with a task's agent."""
    from guild.storage.sqlite import Storage

    db_path = guild_dir / "guild.db"
    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()

    # Check if the task exists and has an assigned agent
    task = await store.get_task(task_id)
    if task is None:
        await store.close()
        return []

    agent_id = task.get("assigned_agent")
    if not agent_id:
        await store.close()
        return []

    messages = await store.get_messages(agent_id)
    await store.close()
    return messages
