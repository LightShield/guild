"""Configuration loader (REQ-01.3).

Finds .guild/ directories, loads config via ConfigsLoader from global
and project config.toml files (project overrides global).
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from guild.config.models import GuildConfig

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable

__all__ = ["ConfigWatcher", "find_guild_dir", "load_config"]

_TEMP_FILE_PREFIX = "guild_config_"

logger = logging.getLogger(__name__)


def find_guild_dir(start: Path | None = None) -> Path | None:
    """Walk up from *start* to locate a .guild/ directory.

    Returns the Path to the .guild directory, or None if not found.
    """
    current = (start or Path.cwd()).resolve()

    while True:
        candidate = current / ".guild"
        if candidate.is_dir():
            return candidate

        parent = current.parent
        if parent == current:
            return None
        current = parent


def _merge_toml_files(guild_dir: Path | None) -> Path | None:
    """Merge global + project TOML into a temp file for ConfigsLoader.

    Resolution order (later overrides earlier):
    1. Global config: ~/.guild/config.toml
    2. Project config: <guild_dir>/config.toml

    Returns path to a merged temp file, or the single available file,
    or None if no config files exist.
    """
    global_path = Path.home() / ".guild" / "config.toml"
    project_path = guild_dir / "config.toml" if guild_dir else None

    global_data = _load_toml_file(global_path)
    project_data = _load_toml_file(project_path) if project_path else {}

    if not global_data and not project_data:
        return None

    # If only one source exists, return it directly
    if not global_data and project_path and project_path.is_file():
        return project_path
    if not project_data and global_path.is_file():
        return global_path

    # Merge: project overrides global
    merged = _deep_merge(global_data, project_data)

    # Write to a temp file in the guild dir (or /tmp)
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".toml", delete=False, prefix=_TEMP_FILE_PREFIX
    ) as tmp:
        _write_toml_bytes(tmp, merged)
    return Path(tmp.name)


def _load_toml_file(path: Path | None) -> dict:
    """Load a TOML file, returning empty dict on failure or missing file."""
    if path is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        logger.debug("Failed to load %s", path, exc_info=True)
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _write_toml_bytes(f, data: dict) -> None:
    """Write a dict as TOML bytes to a file handle."""
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_literal(v)}")

    for section, values in tables.items():
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {_toml_literal(v)}")

    lines.append("")
    f.write("\n".join(lines).encode())


def _toml_literal(value) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def load_config(
    guild_dir: Path | None = None,
    args: list[str] | None = None,
) -> GuildConfig:
    """Load and merge configuration, returning a GuildConfig.

    Resolution order (highest priority first — handled by ConfigsLoader):
    1. CLI arguments (from args)
    2. Environment variables
    3. Config file (merged global + project TOML)
    4. Default values

    Args:
        guild_dir: Path to .guild/ directory for project config.
        args: CLI arguments for flag parsing. Defaults to empty (no CLI parsing).
    """
    merged_file = _merge_toml_files(guild_dir)

    config = GuildConfig.load(
        args=args if args is not None else [],
        file=merged_file,
    )

    # Clean up temp file if we created one
    if merged_file and _TEMP_FILE_PREFIX in str(merged_file):
        import contextlib

        with contextlib.suppress(OSError):
            merged_file.unlink()

    return config  # type: ignore[return-value]


class ConfigWatcher:
    """Watch config file for changes and reload on mtime change (REQ-14.6).

    Call check_for_changes() periodically (e.g., each agent loop iteration).
    If the file's mtime has changed, reloads config and invokes the callback.
    """

    def __init__(self, config_path: Path, callback: Callable) -> None:
        self._config_path = config_path
        self._callback = callback
        self._last_mtime: float | None = self._get_mtime()

    def _get_mtime(self) -> float | None:
        """Return file modification time, or None if file missing."""
        if self._config_path.is_file():
            return self._config_path.stat().st_mtime
        return None

    def check_for_changes(self) -> bool:
        """Check mtime. If changed, reload and call callback.

        Returns True if the config was reloaded, False otherwise.
        """
        current_mtime = self._get_mtime()
        if current_mtime is None:
            return False
        if current_mtime == self._last_mtime:
            return False

        self._last_mtime = current_mtime
        self._callback()
        logger.info("Config reloaded from %s", self._config_path)
        return True
