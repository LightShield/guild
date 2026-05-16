"""Daemon and server CLI commands — serve (web GUI/API) and eval subcommands.

Registers commands on the shared Typer ``app`` instance from guild.cli.main.
"""

# ruff: noqa: B008, UP045 — Typer requires function calls in argument defaults
# and Optional[] syntax (does not support X | None with runtime introspection).

import typer
from rich.console import Console
from rich.table import Table

from guild.cli.main import app
from guild.config.constants import DEFAULT_API_PORT
from guild.config.loader import find_guild_dir
from guild.task.spec import TaskStatus

__all__ = ["confidence", "serve"]

console = Console()


# ------------------------------------------------------------------
# Server command
# ------------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    port: int = typer.Option(DEFAULT_API_PORT, "--port", help="Port to serve on."),
) -> None:
    """Start the Guild web GUI and API server (REQ-05.5)."""
    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    try:  # pragma: no cover — server entry point
        import uvicorn

        from guild.api.server import create_app as _create_app
    except ImportError:
        console.print("[red]Error:[/red] Install API dependencies: pip install guild[api]")
        raise typer.Exit(code=1) from None

    web_app = _create_app(guild_dir=guild_dir)  # pragma: no cover — server entry point
    console.print(f"[bold]Guild GUI[/bold] at http://{host}:{port}")  # pragma: no cover
    uvicorn.run(web_app, host=host, port=port, log_level="info")  # pragma: no cover


# ------------------------------------------------------------------
# Eval subcommand group (REQ-16.6)
# ------------------------------------------------------------------

eval_app = typer.Typer(name="eval", help="Evaluation and benchmarking commands.")
app.add_typer(eval_app)


@eval_app.command()
def confidence() -> None:
    """Display progressive confidence scores per capability area (REQ-16.6)."""
    from guild.eval.framework import SELF_DEV_BENCHMARKS

    guild_dir = find_guild_dir()
    if guild_dir is None:
        console.print("[red]Error:[/red] Not a guild project (no .guild/ found).")
        raise typer.Exit(code=1)

    categories: dict[str, list[str]] = {}
    for bench in SELF_DEV_BENCHMARKS:
        categories.setdefault(bench.category, []).append(bench.name)

    table = Table(title="Eval Confidence by Category")
    table.add_column("Category", style="cyan")
    table.add_column("Tasks", style="white")
    table.add_column("Confidence", style="yellow")

    for category, task_names in sorted(categories.items()):
        table.add_row(
            category,
            str(len(task_names)),
            TaskStatus.PENDING.value,
        )

    console.print(table)
