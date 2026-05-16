"""Guild CLI package."""

from guild.cli.main import app

__all__ = ["app"]

# Command modules (imported by main.py to register @app.command handlers):
# guild.cli.task_commands — task, chat, attach, ps, kill, pause, resume, logs, history
# guild.cli.config_commands — init, status, config, audit, decisions, questions, etc.
# guild.cli.team_commands — team orchestration
# guild.cli.daemon_commands — serve, eval subcommands
#
# Helper modules:
# guild.cli.daemon_ops — background task and process lifecycle operations
# guild.cli.queries — database read helpers for CLI display
# guild.cli.task_runner — agent loop creation, task execution, learning injection
# guild.cli.toml_utils — TOML config file read/write utilities
