"""Configuration loader (REQ-01.3).

Finds .guild/ directories, loads config via ConfigsLoader from global
and project config.toml files (project overrides global).
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from guild.config.models import GuildConfig

__all__ = ["find_guild_dir", "load_config"]

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
        mode="wb", suffix=".toml", delete=False, prefix="guild_config_"
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
        logger.warning("Failed to parse TOML file: %s", path)
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
    if merged_file and "_guild_config_" in str(merged_file):
        import contextlib

        with contextlib.suppress(OSError):
            merged_file.unlink()

    return config  # type: ignore[return-value]
