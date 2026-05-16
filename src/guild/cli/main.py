"""Guild CLI — Typer app instance and version callback.

The ``app`` object is the single entry point (guild.cli.main:app).  Command
functions are registered by importing the command-group modules at the bottom
of this file.
"""

# ruff: noqa: B008, UP045, E402, F401 — Typer requires function calls in
# argument defaults and Optional[] syntax; bottom imports are intentional.
# Note: do NOT use `from __future__ import annotations` — Typer 0.9
# requires runtime type annotation introspection.

import logging

import typer
from rich.console import Console

from guild import __version__

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
# Version / help callback
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
    if ctx.invoked_subcommand is None:  # pragma: no cover — typer handles internally
        console.print(ctx.get_help())
        raise typer.Exit()


# ------------------------------------------------------------------
# Import command modules so they register their @app.command() handlers.
# These imports MUST remain at the bottom to avoid circular imports
# (each module imports `app` from this file).
# ------------------------------------------------------------------

import guild.cli.config_commands
import guild.cli.daemon_commands
import guild.cli.task_commands
import guild.cli.team_commands
