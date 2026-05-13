"""TOML configuration file utilities for the Guild CLI.

Handles reading, writing, and modifying TOML config files with
simple type preservation.  Delegates TOML serialization to
config/loader.py (the canonical lower-layer implementation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from guild.config.loader import toml_literal as toml_value
from guild.config.loader import write_toml_bytes

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "load_toml",
    "parse_value",
    "set_config_value",
    "toml_value",
    "write_toml",
]


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on failure or missing."""
    import tomllib

    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover
        return {}


def set_config_value(config_path: Path, key_value: str) -> None:
    """Set a dotted key=value in a TOML config file.

    Supports dotted keys like 'provider.model=llama3'.
    """
    if "=" not in key_value:
        raise ValueError("Use format key=value")

    key, value = key_value.split("=", 1)
    parts = key.strip().split(".")

    existing = load_toml(config_path)

    current = existing
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    current[parts[-1]] = parse_value(value.strip())

    write_toml(config_path, existing)


def parse_value(value: str) -> str | int | float | bool:
    """Parse a string value into its likely Python type."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write a dict to a TOML file.

    Delegates to the canonical write_toml_bytes in config/loader.py.
    """
    import io

    buf = io.BytesIO()
    write_toml_bytes(buf, data)
    path.write_text(buf.getvalue().decode())
