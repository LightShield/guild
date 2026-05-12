# Learning tests — verify assumptions about typer behavior.
# If these break on upgrade, our code likely needs updating.
#
# Guild depends on:
#   - CliRunner for testing CLI commands
#   - Option defaults work when not provided
#   - Required Arguments raise on missing
#   - no_args_is_help=True shows help when invoked without commands
#
# Key typer behavior: a single-command app invokes the command directly
# (no subcommand name needed). Multi-command apps use subcommand names
# and no_args_is_help shows help when no subcommand is given.

from __future__ import annotations

from typing import Optional  # noqa: UP035 — Typer requires Optional at runtime

import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


def _make_single_command_app() -> typer.Typer:
    """Build a single-command Typer app (typical for simple CLIs)."""
    app = typer.Typer()

    @app.command()
    def greet(
        name: str = typer.Argument(..., help="Name to greet"),
        greeting: str = typer.Option("Hello", help="Greeting word"),
    ) -> None:
        typer.echo(f"{greeting}, {name}!")

    return app


def _make_multi_command_app() -> typer.Typer:
    """Build a multi-command Typer app (how Guild CLI works)."""
    app = typer.Typer(no_args_is_help=True)

    @app.command("run")
    def run_cmd(
        task: str = typer.Argument(..., help="Task description"),
    ) -> None:
        typer.echo(f"Running: {task}")

    @app.command("status")
    def status_cmd() -> None:
        typer.echo("All clear")

    return app


@pytest.mark.learning
class TestCliRunnerCapturesOutput:
    """Verify CliRunner captures stdout — used for CLI testing."""

    def test_cli_runner_captures_output(self) -> None:
        app = _make_single_command_app()
        result = runner.invoke(app, ["World"])
        assert result.exit_code == 0
        assert "Hello, World!" in result.output

    def test_cli_runner_captures_error_exit_code(self) -> None:
        app = _make_single_command_app()
        # Missing required argument should produce non-zero exit code
        result = runner.invoke(app, [])
        assert result.exit_code != 0


@pytest.mark.learning
class TestOptionDefaultUsedWhenNotProvided:
    """Verify Option defaults apply — used throughout Guild CLI."""

    def test_option_default_used_when_not_provided(self) -> None:
        app = _make_single_command_app()
        result = runner.invoke(app, ["Alice"])
        assert result.exit_code == 0
        assert "Hello, Alice!" in result.output

    def test_option_override_works(self) -> None:
        app = _make_single_command_app()
        result = runner.invoke(app, ["Alice", "--greeting", "Hi"])
        assert result.exit_code == 0
        assert "Hi, Alice!" in result.output


@pytest.mark.learning
class TestArgumentRequiredRaisesOnMissing:
    """Verify required Argument raises when missing — contract for positional args."""

    def test_argument_required_raises_on_missing(self) -> None:
        app = _make_single_command_app()
        result = runner.invoke(app, [])
        assert result.exit_code != 0
        # Typer should mention the missing argument in error output
        assert "name" in result.output.lower() or "missing" in result.output.lower()

    def test_multi_command_missing_subcommand_arg(self) -> None:
        app = _make_multi_command_app()
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0
        assert "task" in result.output.lower() or "missing" in result.output.lower()


@pytest.mark.learning
class TestCallbackInvokeWithoutCommand:
    """Verify no_args_is_help=True shows help — Guild uses this pattern."""

    def test_callback_invoke_without_command(self) -> None:
        app = _make_multi_command_app()
        result = runner.invoke(app, [])
        # With no_args_is_help=True and no args, should show help (exit 0)
        assert result.exit_code == 0
        assert "Usage" in result.output or "usage" in result.output.lower()
        # Should list available commands
        assert "run" in result.output
        assert "status" in result.output

    def test_version_callback_pattern(self) -> None:
        """Verify the version callback pattern Guild uses works."""
        app = typer.Typer()

        def version_callback(value: bool) -> None:
            if value:
                typer.echo("v0.1.0")
                raise typer.Exit()

        @app.callback(invoke_without_command=True)
        def main(
            version: Optional[bool] = typer.Option(  # noqa: UP045 — Typer requires Optional
                None, "--version", callback=version_callback, is_eager=True
            ),
        ) -> None:
            pass

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "v0.1.0" in result.output
