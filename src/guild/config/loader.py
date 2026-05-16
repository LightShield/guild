"""Configuration loader (REQ-01.3).

Finds .guild/ directories, loads config via ConfigsLoader from global
and project config.toml files (project overrides global).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from guild.config.constants import CONFIG_FILENAME, DB_FILENAME, GUILD_DIR_NAME
from guild.config.models import GuildConfig
from logger_python import get_logger

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable
    from typing import IO

__all__ = [
    "CONFIG_FILENAME",
    "ConfigWatcher",
    "DB_FILENAME",
    "GUILD_DIR_NAME",
    "NON_RELOADABLE_FIELDS",
    "RELOADABLE_FIELDS",
    "find_guild_dir",
    "load_config",
    "toml_literal",
    "validate_config_keys",
    "write_toml_bytes",
]
_TEMP_FILE_PREFIX = "guild_config_"

logger = get_logger(__name__)


def find_guild_dir(start: Path | None = None) -> Path | None:
    """Walk up from *start* to locate a .guild/ directory.

    Returns the Path to the .guild directory, or None if not found.
    """
    current = (start or Path.cwd()).resolve()

    while True:
        candidate = current / GUILD_DIR_NAME
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
    global_path = Path.home() / GUILD_DIR_NAME / CONFIG_FILENAME
    project_path = guild_dir / CONFIG_FILENAME if guild_dir else None

    global_data = _load_toml_file(global_path)
    project_data = _load_toml_file(project_path) if project_path else {}

    if not global_data and not project_data:
        return None

    if not global_data and project_path and project_path.is_file():
        return project_path
    if not project_data and global_path.is_file():
        return global_path

    merged = _deep_merge(global_data, project_data)

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".toml", delete=False, prefix=_TEMP_FILE_PREFIX
    ) as tmp:
        write_toml_bytes(tmp, merged)
    return Path(tmp.name)


def _load_toml_file(path: Path | None) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on failure or missing file."""
    if path is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.debug("Failed to load %s", path, exc_info=True)
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def write_toml_bytes(f: IO[bytes], data: dict[str, Any]) -> None:
    """Write a dict as TOML bytes to a file handle.

    This is the canonical TOML serialization for Guild config.
    Used by both the config merger and CLI toml_utils.
    """
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    for k, v in scalars.items():
        lines.append(f"{k} = {toml_literal(v)}")

    for section, values in tables.items():
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {toml_literal(v)}")

    lines.append("")
    f.write("\n".join(lines).encode())


def toml_literal(value: Any) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


# Backward-compatible aliases for tests/internal usage
_write_toml_bytes = write_toml_bytes
_toml_literal = toml_literal


def validate_config_keys(guild_dir: Path | None) -> list[str]:
    """Check for unknown config keys in the TOML file.

    Returns a list of warning strings for unknown keys.
    """
    if guild_dir is None:
        return []

    config_path = guild_dir / CONFIG_FILENAME
    raw = _load_toml_file(config_path)
    if not raw:
        return []

    known: dict[str, set[str]] = {}
    for field_name, field_obj in GuildConfig._fields.items():
        section = getattr(field_obj, "section", "") or ""
        if section:  # pragma: no branch — all config fields have a section
            known.setdefault(section, set()).add(field_name)

    warnings: list[str] = []
    for section, values in raw.items():
        if not isinstance(values, dict):
            continue
        section_known = known.get(section, set())
        for key in values:
            if key not in section_known:
                msg = f"Unknown config key '{section}.{key}'"
                warnings.append(msg)
                logger.warning(msg)
    return warnings


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

    if merged_file and _TEMP_FILE_PREFIX in str(merged_file):
        import contextlib

        with contextlib.suppress(OSError):
            merged_file.unlink()

    return config  # type: ignore[no-any-return]


# Fields that can be hot-reloaded without restart
RELOADABLE_FIELDS: set[str] = {
    "default_permission",
    "autonomy_timeout_minutes",
    "stuck_max_repeated_errors",
    "stuck_max_no_progress_turns",
    "stuck_max_repeated_calls",
    "shell_timeout_seconds",
    "shell_max_output_chars",
    "resource_mode",
}

# Fields that require a restart to take effect
NON_RELOADABLE_FIELDS: set[str] = {
    "provider_name",
    "base_url",
    "model",
    "temperature",
    "max_tokens",
    "escalation_chain",
    "escalation_cli_providers",
}


class ConfigWatcher:
    """Watch config file for changes and reload on mtime change (REQ-14.6).

    Call check_for_changes() periodically (e.g., each agent loop iteration).
    If the file's mtime has changed, reloads config and invokes the callback.
    """

    def __init__(self, config_path: Path, callback: Callable[[], None]) -> None:
        """Initialize ConfigWatcher."""
        self._config_path = config_path
        self._callback = callback
        self._last_mtime: float | None = self._get_mtime()
        self._last_config: GuildConfig | None = None
        self._non_reloadable_warnings: list[str] = []

    @property
    def non_reloadable_warnings(self) -> list[str]:
        """Warnings about non-reloadable config changes since last check."""
        return list(self._non_reloadable_warnings)

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
        self._non_reloadable_warnings = []

        # Detect non-reloadable changes
        guild_dir = self._config_path.parent
        new_config = load_config(guild_dir)
        if self._last_config is not None:
            self._detect_non_reloadable_changes(new_config)
        self._last_config = new_config

        self._callback()
        logger.debug("Config reloaded from %s", self._config_path)
        return True

    def _detect_non_reloadable_changes(self, new_config: GuildConfig) -> None:
        """Detect changes to non-reloadable fields and emit warnings."""
        for field_name in NON_RELOADABLE_FIELDS:
            old_val = getattr(self._last_config, field_name, None)
            new_val = getattr(new_config, field_name, None)
            if old_val != new_val:
                msg = f"restart required for {field_name} to take effect"
                self._non_reloadable_warnings.append(msg)
                logger.warning(msg)
