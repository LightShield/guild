"""TOML configuration loader (REQ-01.3).

Finds .guild/ directories, loads global and project config.toml files,
merges them (project overrides global), and returns a GuildConfig.
"""

from __future__ import annotations

import logging
from pathlib import Path

from guild.config.models import GuildConfig

__all__ = ["find_guild_dir", "load_config", "load_toml"]

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


def load_toml(path: Path) -> dict:
    """Load a TOML file and return its contents as a dict.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        return {}

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover — Python < 3.11 fallback
        import tomli as tomllib  # type: ignore[no-redef,import-not-found]

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


def load_config(guild_dir: Path | None = None) -> GuildConfig:
    """Load and merge configuration, returning a GuildConfig.

    Resolution order (later overrides earlier):
    1. Defaults (built into model)
    2. Global config: ~/.guild/config.toml
    3. Project config: <guild_dir>/config.toml
    """
    # Global config
    global_path = Path.home() / ".guild" / "config.toml"
    global_data = load_toml(global_path)

    # Project config
    project_data: dict = {}
    if guild_dir is not None:
        project_path = guild_dir / "config.toml"
        project_data = load_toml(project_path)

    # Merge: project overrides global
    merged = _deep_merge(global_data, project_data)

    # Build GuildConfig from merged data
    provider_data = merged.get("provider", {})
    guild_data = merged.get("guild", {})

    # Flatten guild-level keys into the top-level config
    config_kwargs: dict = {}
    if provider_data:
        config_kwargs["provider"] = provider_data
    config_kwargs.update(guild_data)

    return GuildConfig(**config_kwargs)
