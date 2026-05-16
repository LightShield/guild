"""Task lifecycle CLI commands — task, chat, attach, ps, kill, pause, resume, logs, history.

Registers commands on the shared Typer ``app`` instance from guild.cli.main.
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from guild.cli.daemon_ops import (
    create_task_in_storage as _create_task_in_storage,
)
from guild.cli.daemon_ops import (
    get_running_tasks as _get_running_tasks,
)
from guild.cli.daemon_ops import (
    kill_all_tasks as _kill_all_tasks,
)
from guild.cli.daemon_ops import (
    kill_task as _kill_task,
)
from guild.cli.daemon_ops import (
    launch_background_task as _launch_background_task,
)
from guild.cli.daemon_ops import (
    pause_task as _pause_task,
)
from guild.cli.daemon_ops import (
    resume_task as _resume_task,
)
from guild.cli.main import app
from guild.cli.queries import (
    fetch_task_history as _fetch_task_history,
)
from guild.cli.queries import (
    fetch_task_messages as _fetch_task_messages,
)
from guild.cli.task_runner import (
    GUILD_MASTER_PROMPT as _GUILD_MASTER_PROMPT,
)
from guild.cli.task_runner import (
    create_chat_loop as _create_chat_loop,
)
from guild.cli.task_runner import (
    run_task as _run_task,
)
from guild.config.constants import (
    CLI_DESC_COL_WIDTH,
    CLI_ID_COL_WIDTH,
    CLI_RESULT_COL_WIDTH,
)
from guild.config.loader import (
    DB_FILENAME,
    find_guild_dir,
    load_config,
)
from guild.permissions.checker import PermissionTier
from guild.task.spec import TaskStatus

__all__ = [
    "attach",
    "chat",
    "history",
    "kill",
    "logs",
    "pause",
    "ps_cmd",
    "resume",
    "task",
]

console = Console()


# ------------------------------------------------------------------
# Task execution commands
# ------------------------------------------------------------------


@app.command()
def task(
    description: str = typer.Argument(..., help="Task description."),
    permission: str = typer.Option(
        PermissionTier.AUTOPILOT.value, "--permission", "-p", help="Permission tier."
    ),
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
    permission: str = typer.Option(
        PermissionTier.ASK.value, "--permission", "-p", help="Permission tier."
    ),
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

    try:  # pragma: no cover — interactive I/O
        loop = _create_chat_loop(config, working_dir, permission)
        first_turn = True

        while True:
            user_input = console.input("[bold blue]> [/bold blue]")
            if not user_input.strip():
                continue

            if first_turn:
                result = asyncio.run(loop.run(_GUILD_MASTER_PROMPT, user_input))
                first_turn = False
            else:
                result = asyncio.run(loop.send(user_input))

            console.print(f"\n{result}\n")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Goodbye.[/dim]")


@app.command()
def attach(
    task_id: str = typer.Argument(..., help="Task ID to attach to."),
) -> None:
    """Attach to a running task (interactive)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    run_dir = guild_dir / "run"
    sock_path = run_dir / f"{task_id}.sock"

    if not sock_path.exists():
        console.print(f"[red]Error:[/red] Task not running (no control socket at {sock_path}).")
        raise typer.Exit(code=1)

    asyncio.run(_attach_repl(sock_path, task_id))  # pragma: no cover — interactive I/O


async def _attach_repl(
    sock_path: "Path", task_id: str
) -> None:  # pragma: no cover — interactive I/O
    """Connect to the task socket and run the interactive REPL."""
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    if not await _subscribe_to_task(reader, writer):
        return

    console.print(f"[bold green]Attached to task {task_id}[/bold green] (Ctrl+C to detach)")

    try:
        await asyncio.gather(
            _read_task_responses(reader),
            _send_user_input(writer),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()
        console.print("[dim]Detached.[/dim]")


async def _subscribe_to_task(  # pragma: no cover — interactive I/O
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> bool:
    """Send subscribe command and verify acknowledgement."""
    writer.write(json.dumps({"type": "command", "action": "subscribe"}).encode() + b"\n")
    await writer.drain()
    ack = await reader.readline()
    ack_data = json.loads(ack)
    if ack_data.get("status") != "subscribed":
        console.print("[red]Error:[/red] Failed to subscribe to task output.")
        writer.close()
        await writer.wait_closed()
        return False
    return True


async def _read_task_responses(
    reader: asyncio.StreamReader,
) -> None:  # pragma: no cover — interactive I/O
    """Read and display responses from the agent."""
    while True:
        line = await reader.readline()
        if not line:
            console.print("[dim]Connection closed.[/dim]")
            break
        data = json.loads(line)
        msg_type = data.get("type", "")
        content = data.get("content", "")
        if msg_type == "agent_message":
            console.print(f"[bold]agent:[/bold] {content}")
        else:
            console.print(f"[dim]{data}[/dim]")


async def _send_user_input(
    writer: asyncio.StreamWriter,
) -> None:  # pragma: no cover — interactive I/O
    """Read user input and send as messages."""
    import sys

    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
        except EOFError:
            break
        if not line:
            break
        msg = json.dumps({"type": "message", "content": line.strip()})
        writer.write(msg.encode() + b"\n")
        await writer.drain()


# ------------------------------------------------------------------
# Process lifecycle commands
# ------------------------------------------------------------------


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
        table.add_row(t["task_id"], str(t["pid"]), TaskStatus.RUNNING.value)

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
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of tasks to show."),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    task_id: Optional[str] = typer.Option(None, "--task", "-t", help="Show subtasks of a task."),
    tree: bool = typer.Option(False, "--tree", help="Show parent-child task tree."),
) -> None:
    """Browse past tasks and their outcomes (REQ-07.9)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME

    if task_id and tree:
        _render_task_tree(db_path, task_id)
        return

    tasks = asyncio.run(_fetch_task_history(db_path, limit, status))

    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return

    table = Table(title="Task History")
    table.add_column("Task ID", style="cyan", max_width=CLI_ID_COL_WIDTH)
    table.add_column("Status", style="yellow")
    table.add_column("Description", style="white")
    table.add_column("Created", style="dim")
    table.add_column("Result", style="green", max_width=CLI_RESULT_COL_WIDTH)

    for t in tasks:
        table.add_row(
            t.get("task_id", "")[:CLI_ID_COL_WIDTH],
            t.get("status", ""),
            t.get("description", ""),
            t.get("created_at", ""),
            (t.get("result") or "")[:CLI_RESULT_COL_WIDTH],
        )

    console.print(table)


def _render_task_tree(db_path: Path, root_task_id: str) -> None:
    """Render parent-child task relationships as indented tree (REQ-12.3)."""
    from guild.storage.sqlite import Storage

    async def _fetch_tree() -> list[dict[str, Any]]:
        async with Storage(db_path) as store:
            return await store.list_tasks()

    tasks = asyncio.run(_fetch_tree())

    children_map: dict[str, list[dict[str, Any]]] = {}
    task_map: dict[str, dict[str, Any]] = {}
    for t in tasks:
        tid = t.get("task_id", "")
        task_map[tid] = t
        parent = t.get("parent_id")
        if parent:  # pragma: no cover — parent_id not yet in DB schema
            children_map.setdefault(parent, []).append(t)

    if root_task_id not in task_map:
        console.print(f"[red]Error:[/red] Task {root_task_id} not found.")
        raise typer.Exit(code=1)

    def _print_node(tid: str, indent: int) -> None:
        t = task_map.get(tid)
        if t is None:  # pragma: no cover — defensive guard
            return
        prefix = "  " * indent
        desc = t.get("description", "")[:CLI_DESC_COL_WIDTH]
        status = t.get("status", "")
        console.print(f"{prefix}{tid[:12]} [{status}] {desc}")
        for child in children_map.get(tid, []):  # pragma: no cover — parent_id not yet in DB
            _print_node(child["task_id"], indent + 1)

    console.print("[bold]Task Tree[/bold]")
    _print_node(root_task_id, 0)
