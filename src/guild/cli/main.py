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
from typing import Any, Optional

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
    "You are an autonomous coding agent. You MUST use the provided tools to complete tasks. "
    "Do NOT respond with text alone — always use tools to take action.\n\n"
    "Available tools: file_read (read files), file_write (write/create files), "
    "shell (run commands), search (grep files), glob (find files).\n\n"
    "Workflow:\n"
    "1. Read relevant files to understand the codebase\n"
    "2. Make changes using file_write\n"
    "3. Verify your changes work (run tests if applicable)\n"
    "4. Provide a brief summary of what you accomplished\n\n"
    "IMPORTANT: Start by reading files. Never guess at file contents."
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

    db_path = guild_dir / "guild.db"
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

    db_path = guild_dir / "guild.db"

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
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of tasks to show."),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
) -> None:
    """Browse past tasks and their outcomes (REQ-07.9)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / "guild.db"
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

    db_path = guild_dir / "guild.db"
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

    db_path = guild_dir / "guild.db"
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

    db_path = guild_dir / "guild.db"
    asyncio.run(_answer_pending_question(db_path, question_id, response))
    console.print(f"[green]Answered question:[/green] {question_id[:12]}")


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


def _create_chat_loop(config: Any, working_dir: str, permission: str) -> Any:
    """Create an AgentLoop instance for interactive chat (REQ-06.9)."""
    from guild.agent.loop import AgentLoop
    from guild.permissions.checker import PermissionChecker, PermissionTier
    from guild.tools.file_ops import execute_file_read, execute_file_write
    from guild.tools.search import execute_glob, execute_search
    from guild.tools.shell import execute_shell

    provider = create_provider(config.base_url, config.model)
    tool_executors = {
        "file_read": execute_file_read,
        "file_write": execute_file_write,
        "shell": execute_shell,
        "search": execute_search,
        "glob": execute_glob,
    }

    tier = PermissionTier(permission)
    _checker = PermissionChecker(tier=tier)

    return AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=50,
    )


def _build_provider(config: Any) -> Any:
    """Build an LLM provider, with escalation chain if configured."""
    from guild.provider.escalation import EscalatingProvider, EscalationChain

    primary = create_provider(config.base_url, config.model)

    chain_models = [m.strip() for m in config.escalation_chain.split(",") if m.strip()]
    cli_tools = [t.strip() for t in config.escalation_cli_providers.split(",") if t.strip()]

    if not chain_models and not cli_tools:
        return primary

    providers = [primary]
    for model_name in chain_models:
        if model_name != config.model:
            providers.append(create_provider(config.base_url, model_name))

    if cli_tools:
        from guild.provider.cli_provider import CLIToolProvider

        for tool_cmd in cli_tools:
            providers.append(CLIToolProvider(command=tool_cmd))

    chain = EscalationChain(providers)
    return EscalatingProvider(chain)


_DEFAULT_MAX_TURNS = 50
_SECONDS_PER_TURN_ESTIMATE = 10
_MIN_TURNS = 5
_MAX_TURNS_CAP = 200
_LEARNING_MIN_CONFIDENCE = 0.5


async def _run_task(
    config: Any,
    working_dir: str,
    description: str,
    permission: str,
    timeout: int,
    guild_dir: Path,
) -> str:
    """Execute a task through the agent loop."""
    from guild.storage.sqlite import Storage

    db_path = guild_dir / "guild.db"
    store = Storage(db_path)
    await store.connect()

    try:
        loop = _create_task_agent_loop(config, working_dir, timeout)
        system_prompt = await _build_system_prompt_with_learnings(store)
        result = await loop.run(system_prompt, description)
        await _persist_task_result(store, loop, description, result, config)
        await _extract_post_task_learnings(store, loop, config)
    finally:
        await store.close()

    return result


def _create_task_agent_loop(config: Any, working_dir: str, timeout: int) -> Any:
    """Build an AgentLoop configured for task execution."""
    from guild.agent.loop import AgentLoop
    from guild.agent.stuck import StuckDetector
    from guild.tools.file_ops import execute_file_read, execute_file_write
    from guild.tools.search import execute_glob, execute_search
    from guild.tools.shell import execute_shell

    provider = _build_provider(config)
    tool_executors = {
        "file_read": execute_file_read,
        "file_write": execute_file_write,
        "shell": execute_shell,
        "search": execute_search,
        "glob": execute_glob,
    }

    max_turns = _compute_max_turns(timeout)
    stuck_detector = StuckDetector(
        max_repeated_errors=config.stuck_max_repeated_errors,
        max_no_progress_turns=config.stuck_max_no_progress_turns,
        max_repeated_calls=config.stuck_max_repeated_calls,
    )

    return AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=max_turns,
        stuck_detector=stuck_detector,
    )


def _compute_max_turns(timeout: int) -> int:
    """Convert a timeout in seconds to a max turn count."""
    if timeout <= 0:
        return _DEFAULT_MAX_TURNS
    return min(max(timeout // _SECONDS_PER_TURN_ESTIMATE, _MIN_TURNS), _MAX_TURNS_CAP)


async def _build_system_prompt_with_learnings(store: Any) -> str:
    """Build the system prompt, injecting high-confidence learnings (REQ-09.4)."""
    system_prompt = _GUILD_MASTER_PROMPT
    try:
        from guild.agent.learning import format_learnings_for_injection

        existing_learnings = await store.list_learnings(min_confidence=_LEARNING_MIN_CONFIDENCE)
        injection = format_learnings_for_injection(existing_learnings)
        if injection:
            system_prompt = f"{system_prompt}\n\n{injection}"
    except Exception:
        logger.debug("Learning injection failed (non-critical)", exc_info=True)
    return system_prompt


async def _persist_task_result(
    store: Any, loop: Any, description: str, result: str, config: Any
) -> None:
    """Save task, agent, messages, and audit entry to storage."""
    import uuid

    task_id = str(uuid.uuid4())
    agent_id = f"guild-master-{task_id[:8]}"

    await store.create_task(task_id, description)
    await store.update_task(task_id, status="completed", result=result, assigned_agent=agent_id)
    await store.register_agent(agent_id, "master")
    await store.update_agent(
        agent_id,
        token_input=str(loop.total_input_tokens),
        token_output=str(loop.total_output_tokens),
    )

    for msg in loop.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role and content:
            await store.append_message(agent_id, role, content)

    await store.log_audit(
        action="task_completed",
        agent_id=agent_id,
        details=f"task={task_id} tokens_in={loop.total_input_tokens}"
        f" tokens_out={loop.total_output_tokens}",
    )


async def _extract_post_task_learnings(store: Any, loop: Any, config: Any) -> None:
    """Extract learnings from the completed task (REQ-09.1)."""
    try:
        from guild.agent.learning import extract_learnings

        provider = _build_provider(config)
        # Use the first task ID from storage — extract_learnings uses it for context
        tasks = await store.list_tasks()
        if tasks:
            task_id = tasks[-1].get("task_id", "")
            await extract_learnings(task_id, store, provider)
    except Exception:
        logger.debug("Learning extraction failed (non-critical)", exc_info=True)


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


async def _fetch_decisions(
    db_path: Path,
    task_id: str | None,
    limit: int,
) -> list[dict]:
    """Fetch decision log entries from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_decisions(task_id=task_id, limit=limit)
    await store.close()
    return entries


async def _fetch_task_history(db_path: Path, limit: int, status: str | None) -> list[dict]:
    """Fetch task history from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()
    tasks = await store.list_tasks(status=status)
    await store.close()
    # Return most recent first, capped at limit
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks[:limit]


async def _fetch_token_summary(db_path: Path) -> dict | None:
    """Fetch token usage summary from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return None

    store = Storage(db_path)
    await store.connect()
    summary = await store.get_token_summary()
    await store.close()
    return summary


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


def _toml_value(value: Any) -> str:
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


# ------------------------------------------------------------------
# Learnings helpers
# ------------------------------------------------------------------


async def _fetch_learnings(
    db_path: Path,
    category: str | None,
    limit: int,
) -> list[dict]:
    """Fetch learnings from the database."""
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()
    entries = await store.list_learnings(category=category, limit=limit)
    await store.close()
    return entries


async def _approve_learning(db_path: Path, learning_id: int) -> None:
    """Validate (approve) a learning, boosting its confidence."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    await store.validate_learning(learning_id)
    await store.close()


async def _reject_learning(db_path: Path, learning_id: int) -> None:
    """Delete a rejected learning."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    await store.delete_learning(learning_id)
    await store.close()


async def _decay_learnings(db_path: Path) -> int:
    """Run decay on old unvalidated learnings."""
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    count = await store.decay_learnings()
    await store.close()
    return count


# ------------------------------------------------------------------
# Escalation helpers (REQ-15.1)
# ------------------------------------------------------------------


async def _fetch_pending_questions(db_path: Path) -> list:
    """Fetch pending escalation questions from the database."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    if not db_path.exists():
        return []

    store = Storage(db_path)
    await store.connect()
    queue = QuestionQueue(store)
    pending = await queue.get_pending()
    await store.close()
    return pending


async def _answer_pending_question(db_path: Path, question_id: str, response: str) -> None:
    """Answer a pending escalation question."""
    from guild.escalation.queue import QuestionQueue
    from guild.storage.sqlite import Storage

    store = Storage(db_path)
    await store.connect()
    queue = QuestionQueue(store)
    await queue.answer_question(question_id, response)
    await store.close()
