"""TOML configuration file utilities for the Guild CLI.

Handles reading, writing, and modifying TOML config files with
simple type preservation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "load_toml",
    "parse_value",
    "set_config_value",
    "toml_value",
    "write_toml",
]


def load_toml(path: Path) -> dict:
    """Load a TOML file, returning empty dict on failure or missing."""
    import tomllib

    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:  # pragma: no cover — defensive guard for corrupted TOML
        return {}


def set_config_value(config_path: Path, key_value: str) -> None:
    """Set a dotted key=value in a TOML config file.

    Supports dotted keys like 'provider.model=llama3'.
    """
    if "=" not in key_value:
        raise ValueError("Use format key=value")

    key, value = key_value.split("=", 1)
    parts = key.strip().split(".")

    # Load existing TOML data
    existing = load_toml(config_path)

    # Navigate to the right nested level
    current = existing
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    current[parts[-1]] = parse_value(value.strip())

    # Write back as TOML
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


def write_toml(path: Path, data: dict) -> None:
    """Write a dict to a TOML file (simple implementation)."""
    lines: list[str] = []
    # Separate top-level scalars from tables
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    for k, v in scalars.items():
        lines.append(f"{k} = {toml_value(v)}")

    for section, values in tables.items():
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {toml_value(v)}")

    lines.append("")  # trailing newline
    path.write_text("\n".join(lines))


def toml_value(value: Any) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)
