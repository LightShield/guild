"""Team orchestration CLI commands — multi-agent team execution.

Registers commands on the shared Typer ``app`` instance from guild.cli.main.
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).

import asyncio

import typer
from rich.console import Console

from guild.cli.main import app
from guild.cli.task_runner import (
    run_team_task as _run_team_task,
)
from guild.config.loader import (
    find_guild_dir,
    load_config,
)

__all__ = ["team"]

console = Console()


@app.command()
def team(
    task_description: str = typer.Argument(..., help="Task description for the team."),
    team_name: str = typer.Option("default", "--team", "-t", help="Team name from .guild/teams/."),
    timeout: int = typer.Option(0, "--timeout", help="Timeout in seconds (0=unlimited)."),
) -> None:
    """Run a task using a multi-agent team composition."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    config = load_config(guild_dir)
    working_dir = str(guild_dir.parent)

    result = asyncio.run(
        _run_team_task(config, working_dir, guild_dir, team_name, task_description)
    )
    console.print(f"\n[green]Team done.[/green] {result}")
