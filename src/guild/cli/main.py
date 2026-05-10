"""Guild CLI — Typer-based command-line interface (REQ-05.1, REQ-05.2).

Primary entry point for all Guild operations: init, task, chat, status,
config, and audit commands.  Each command is a thin wrapper that delegates
to helper modules (task_runner, daemon_ops, queries, toml_utils).
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).
# Note: do NOT use `from __future__ import annotations` — Typer 0.9
# requires runtime type annotation introspection.

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from guild import __version__
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
from guild.cli.queries import (
    answer_pending_question as _answer_pending_question,
)
from guild.cli.queries import (
    approve_learning as _approve_learning,
)
from guild.cli.queries import (
    decay_learnings as _decay_learnings,
)
from guild.cli.queries import (
    fetch_audit as _fetch_audit,
)
from guild.cli.queries import (
    fetch_decisions as _fetch_decisions,
)
from guild.cli.queries import (
    fetch_learnings as _fetch_learnings,
)
from guild.cli.queries import (
    fetch_pending_questions as _fetch_pending_questions,
)
from guild.cli.queries import (
    fetch_task_history as _fetch_task_history,
)
from guild.cli.queries import (
    fetch_task_messages as _fetch_task_messages,
)
from guild.cli.queries import (
    fetch_token_summary as _fetch_token_summary,
)
from guild.cli.queries import (
    reject_learning as _reject_learning,
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
from guild.cli.toml_utils import set_config_value as _set_config_value
from guild.config.loader import (
    CONFIG_FILENAME,
    DB_FILENAME,
    GUILD_DIR_NAME,
    find_guild_dir,
    load_config,
)
from guild.permissions.checker import PermissionTier
from guild.task.spec import TaskStatus

__all__ = ["app"]

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="guild",
    help="Guild — autonomous coding agent harness.",
    no_args_is_help=True,
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


# ------------------------------------------------------------------
# Callbacks and commands
# ------------------------------------------------------------------


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

    guild_dir = target / GUILD_DIR_NAME
    if guild_dir.exists():
        console.print(f"[yellow]Already initialized:[/yellow] {guild_dir}")
        raise typer.Exit()

    guild_dir.mkdir(parents=True)

    # Write default config
    config_path = guild_dir / CONFIG_FILENAME
    config_path.write_text(_DEFAULT_CONFIG_TOML)

    # Create the database
    db_path = guild_dir / DB_FILENAME
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
    db_path = guild_dir / DB_FILENAME
    task_count, agent_count = _get_task_and_agent_counts(db_path)

    console.print(f"[bold]Project:[/bold] {project_path}")
    console.print(f"[bold]Provider:[/bold] {config.provider_name}")
    console.print(f"[bold]Model:[/bold] {config.model}")
    console.print(f"[bold]Tasks:[/bold] {task_count}")
    console.print(f"[bold]Agents:[/bold] {agent_count}")


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

    config_path = guild_dir / CONFIG_FILENAME

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

    db_path = guild_dir / DB_FILENAME
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


@app.command()
def decisions(
    task_id: Optional[str] = typer.Option(None, "--task", "-t", help="Filter by task ID."),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries."),
) -> None:
    """Show recent decision log entries."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME
    entries = asyncio.run(_fetch_decisions(db_path, task_id, limit))

    if not entries:
        console.print("[dim]No decisions found.[/dim]")
        return

    table = Table(title="Decision Log")
    table.add_column("Timestamp", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Decision", style="yellow")
    table.add_column("Rationale", style="white")
    table.add_column("Alternatives", style="dim")

    for entry in entries:
        table.add_row(
            entry.get("timestamp", ""),
            entry.get("agent_id", "") or "-",
            entry.get("decision", ""),
            entry.get("rationale", ""),
            entry.get("alternatives", "") or "-",
        )

    console.print(table)


@app.command()
def learnings(
    approve: Optional[int] = typer.Option(None, "--approve", help="Approve a learning by ID."),
    reject: Optional[int] = typer.Option(None, "--reject", help="Reject/delete a learning by ID."),
    decay: bool = typer.Option(False, "--decay", help="Run decay on old unvalidated learnings."),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category."),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries."),
) -> None:
    """Browse, approve, reject, or decay learnings."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME

    if approve is not None:
        asyncio.run(_approve_learning(db_path, approve))
        console.print(f"[green]Approved learning {approve}.[/green]")
        return

    if reject is not None:
        asyncio.run(_reject_learning(db_path, reject))
        console.print(f"[green]Rejected learning {reject}.[/green]")
        return

    if decay:
        count = asyncio.run(_decay_learnings(db_path))
        console.print(f"[green]Decayed {count} learning(s).[/green]")
        return

    entries = asyncio.run(_fetch_learnings(db_path, category, limit))
    if not entries:
        console.print("[dim]No learnings found.[/dim]")
        return

    table = Table(title="Learnings")
    table.add_column("ID", style="dim")
    table.add_column("Category", style="cyan")
    table.add_column("Confidence", style="yellow")
    table.add_column("Content", style="white")
    table.add_column("Validated", style="dim")

    for entry in entries:
        table.add_row(
            str(entry.get("id", "")),
            entry.get("category", ""),
            f"{entry.get('confidence', 0):.2f}",
            entry.get("content", ""),
            str(entry.get("validation_count", 0)),
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
) -> None:
    """Browse past tasks and their outcomes (REQ-07.9)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME
    tasks = asyncio.run(_fetch_task_history(db_path, limit, status))

    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return

    table = Table(title="Task History")
    table.add_column("Task ID", style="cyan", max_width=12)
    table.add_column("Status", style="yellow")
    table.add_column("Description", style="white")
    table.add_column("Created", style="dim")
    table.add_column("Result", style="green", max_width=40)

    for t in tasks:
        table.add_row(
            t.get("task_id", "")[:12],
            t.get("status", ""),
            t.get("description", ""),
            t.get("created_at", ""),
            (t.get("result") or "")[:40],
        )

    console.print(table)


@app.command()
def usage() -> None:
    """Show token usage summary across all tasks (REQ-10.3)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME
    summary = asyncio.run(_fetch_token_summary(db_path))

    if summary is None:
        console.print("[dim]No usage data found.[/dim]")
        return

    total_tokens = summary["total_input"] + summary["total_output"]
    task_count = summary["task_count"]
    avg_per_task = total_tokens // task_count if task_count > 0 else 0

    table = Table(title="Token Usage Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total input tokens", str(summary["total_input"]))
    table.add_row("Total output tokens", str(summary["total_output"]))
    table.add_row("Total tokens", str(total_tokens))
    table.add_row("Tasks", str(task_count))
    table.add_row("Agents", str(summary["agent_count"]))
    table.add_row("Avg tokens/task", str(avg_per_task))

    console.print(table)


@app.command(name="resource-status")
def resource_status_cmd() -> None:
    """Show current resource scheduling mode and system state."""
    from guild.daemon.resource import ResourceMonitor, SchedulingMode

    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    config = load_config(guild_dir)
    monitor = ResourceMonitor(mode=SchedulingMode(config.resource_mode))
    status = monitor.get_status()

    console.print(f"[bold]Mode:[/bold] {status.mode.value}")
    console.print(f"[bold]Activity:[/bold] {status.activity.value}")
    console.print(f"[bold]CPU:[/bold] {status.cpu_percent:.1f}%")
    console.print(f"[bold]Throttled:[/bold] {status.is_throttled}")
    if status.reason:
        console.print(f"[bold]Reason:[/bold] {status.reason}")


@app.command()
def questions(
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries."),
) -> None:
    """List pending escalation questions from agents (REQ-15.1)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME
    entries = asyncio.run(_fetch_pending_questions(db_path))

    if not entries:
        console.print("[dim]No pending questions.[/dim]")
        return

    table = Table(title="Pending Questions")
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Priority", style="yellow")
    table.add_column("Question", style="white")
    table.add_column("Context", style="dim", max_width=40)
    table.add_column("Created", style="dim")

    for q in entries[:limit]:
        table.add_row(
            q.id[:12],
            q.priority.value,
            q.question,
            q.context[:40],
            q.created_at,
        )

    console.print(table)


@app.command()
def answer(
    question_id: str = typer.Argument(..., help="Question ID to answer."),
    response: str = typer.Argument(..., help="Your answer to the question."),
) -> None:
    """Answer a pending escalation question (REQ-15.1)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME
    asyncio.run(_answer_pending_question(db_path, question_id, response))
    console.print(f"[green]Answered question:[/green] {question_id[:12]}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    port: int = typer.Option(8585, "--port", help="Port to serve on."),
) -> None:
    """Start the Guild web GUI and API server (REQ-05.5)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    try:  # pragma: no cover — server entry point
        import uvicorn  # type: ignore[import-untyped]

        from guild.api.server import create_app as _create_app
    except ImportError:
        console.print("[red]Error:[/red] Install API dependencies: pip install guild[api]")
        raise typer.Exit(code=1) from None

    web_app = _create_app(guild_dir=guild_dir)
    console.print(f"[bold]Guild GUI[/bold] at http://{host}:{port}")
    uvicorn.run(web_app, host=host, port=port, log_level="info")


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
# Lightweight local helpers (kept in main.py because they are tiny
# and only used by init/status)
# ------------------------------------------------------------------


def _init_database(db_path: Path) -> None:
    """Create the SQLite database with schema."""
    from guild.storage.sqlite import Storage

    async def _create() -> None:
        async with Storage(db_path):
            pass

    asyncio.run(_create())


def _get_task_and_agent_counts(db_path: Path) -> tuple[int, int]:
    """Get task and agent counts from the database."""
    from guild.storage.sqlite import Storage

    async def _query() -> tuple[int, int]:
        async with Storage(db_path) as store:
            tasks = await store.list_tasks()
            agents = await store.list_agents()
            return len(tasks), len(agents)

    if not db_path.exists():
        return 0, 0

    return asyncio.run(_query())
