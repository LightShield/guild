"""Guild CLI package."""

from guild.cli.main import app

__all__ = ["app"]

# Sub-modules available for direct import:
# guild.cli.daemon_ops — background task and process lifecycle operations
# guild.cli.queries — database read helpers for CLI display
# guild.cli.task_runner — agent loop creation, task execution, learning injection
# guild.cli.toml_utils — TOML config file read/write utilities
