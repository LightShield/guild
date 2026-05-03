"""Configuration loading — TOML files with global/project layering.

Config resolution order: global (~/.guild/config.toml) → project (.guild/config.toml).
Project values override global values.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from guild.core.models import GuildConfig, PermissionTier, ProviderConfig

__all__ = ["find_guild_dir", "load_config", "load_toml"]

GUILD_DIR = ".guild"
CONFIG_NAME = "config.toml"
GLOBAL_DIR = Path.home() / ".guild"


def find_guild_dir(start: Path | None = None) -> Path | None:
    """Walk up from start to find .guild/ directory.

    Args:
        start: Directory to start searching from (default: cwd).

    Returns:
        Path to .guild/ directory, or None if not found.
    """
    cwd = start or Path.cwd()
    for p in [cwd, *cwd.parents]:
        gd = p / GUILD_DIR
        if gd.is_dir():
            return gd
    return None


def load_toml(path: Path) -> dict:
    """Load a TOML file, return empty dict if missing.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed TOML as a dict.
    """
    if path.is_file():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def load_config(guild_dir: Path | None = None) -> GuildConfig:
    """Load config with global → project layering.

    Args:
        guild_dir: Path to the project's .guild/ directory.

    Returns:
        Merged GuildConfig with project overriding global.
    """
    global_raw = load_toml(GLOBAL_DIR / CONFIG_NAME)
    project_raw = load_toml(guild_dir / CONFIG_NAME) if guild_dir else {}

    # Merge: project overrides global
    merged: dict = {**global_raw}
    for section, values in project_raw.items():
        if section in merged and isinstance(merged[section], dict) and isinstance(values, dict):
            merged[section] = {**merged[section], **values}
        else:
            merged[section] = values

    config = GuildConfig()

    if "provider" in merged:
        p = merged["provider"]
        config.provider = ProviderConfig(
            name=p.get("name", config.provider.name),
            base_url=p.get("base_url", config.provider.base_url),
            model=p.get("model", config.provider.model),
            temperature=p.get("temperature", config.provider.temperature),
            max_tokens=p.get("max_tokens", config.provider.max_tokens),
        )

    if "guild" in merged:
        g = merged["guild"]
        if "default_permission" in g:
            config.default_permission = PermissionTier(g["default_permission"])
        if "max_concurrent_agents" in g:
            config.max_concurrent_agents = g["max_concurrent_agents"]
        if "max_concurrent_tool_calls" in g:
            config.max_concurrent_tool_calls = g["max_concurrent_tool_calls"]
        if "autonomy_timeout_minutes" in g:
            config.autonomy_timeout_minutes = g["autonomy_timeout_minutes"]

    if "entry_agent" in merged:
        ea = merged["entry_agent"]
        if "model" in ea:
            config.entry_agent.model = ea["model"]
        if "system_prompt" in ea:
            config.entry_agent.system_prompt = ea["system_prompt"]
        if "tools" in ea:
            config.entry_agent.tools = ea["tools"]
        if "permission" in ea:
            config.entry_agent.permission = PermissionTier(ea["permission"])

    return config
