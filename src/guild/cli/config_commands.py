"""Configuration, status, and knowledge CLI commands.

Covers: init, status, config, audit, decisions, questions, answer, approve,
learnings, usage, resource_status.

Registers commands on the shared Typer ``app`` instance from guild.cli.main.
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).

import asyncio
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from guild.cli.main import _DEFAULT_CONFIG_TOML, app
from guild.cli.queries import (
    answer_pending_question as _answer_pending_question,
)
from guild.cli.queries import (
    approve_all_questions as _approve_all_questions,
)
from guild.cli.queries import (
    approve_learning as _approve_learning,
)
from guild.cli.queries import (
    approve_selected_questions as _approve_selected_questions,
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
    fetch_token_summary as _fetch_token_summary,
)
from guild.cli.queries import (
    reject_learning as _reject_learning,
)
from guild.cli.toml_utils import set_config_value as _set_config_value
from guild.config.loader import (
    CONFIG_FILENAME,
    DB_FILENAME,
    GUILD_DIR_NAME,
    find_guild_dir,
    load_config,
)

__all__ = [
    "answer",
    "approve",
    "audit",
    "config_cmd",
    "decisions",
    "init",
    "learnings",
    "questions",
    "resource_status_cmd",
    "status",
    "usage",
]

console = Console()


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

    config_path = guild_dir / CONFIG_FILENAME
    config_path.write_text(_DEFAULT_CONFIG_TOML)

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

    db_path = guild_dir / DB_FILENAME
    task_count, agent_count = _get_task_and_agent_counts(db_path)

    console.print(f"[bold]Project:[/bold] {project_path}")
    console.print(f"[bold]Provider:[/bold] {config.provider_name}")
    console.print(f"[bold]Model:[/bold] {config.model}")
    console.print(f"[bold]Tasks:[/bold] {task_count}")
    console.print(f"[bold]Agents:[/bold] {agent_count}")


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
        try:
            _set_config_value(config_path, set_value)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]Updated:[/green] {set_value}")
        return

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


# ------------------------------------------------------------------
# Audit, decisions, learnings
# ------------------------------------------------------------------


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

    _display_learnings_table(entries)


def _display_learnings_table(entries: list[dict[str, Any]]) -> None:
    """Render the learnings list as a rich table."""
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


# ------------------------------------------------------------------
# Questions and escalation
# ------------------------------------------------------------------


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
def approve(
    question_ids: Optional[list[str]] = typer.Argument(None, help="Question IDs to approve."),
    all_questions: bool = typer.Option(False, "--all", help="Approve all pending questions."),
) -> None:
    """Approve pending escalation questions (REQ-15.4)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    db_path = guild_dir / DB_FILENAME

    if all_questions:
        count = asyncio.run(_approve_all_questions(db_path))
        console.print(f"[green]Approved {count} question(s).[/green]")
        return

    if question_ids:
        count = asyncio.run(_approve_selected_questions(db_path, question_ids))
        console.print(f"[green]Approved {count} question(s).[/green]")
        return

    console.print("[red]Error:[/red] Provide question IDs or use --all.")
    raise typer.Exit(code=1)


# ------------------------------------------------------------------
# Usage and resource status
# ------------------------------------------------------------------


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
    resource_status = monitor.get_status()

    console.print(f"[bold]Mode:[/bold] {resource_status.mode.value}")
    console.print(f"[bold]Activity:[/bold] {resource_status.activity.value}")
    console.print(f"[bold]CPU:[/bold] {resource_status.cpu_percent:.1f}%")
    console.print(f"[bold]Throttled:[/bold] {resource_status.is_throttled}")
    if resource_status.reason:
        console.print(f"[bold]Reason:[/bold] {resource_status.reason}")


# ------------------------------------------------------------------
# Local helpers
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
