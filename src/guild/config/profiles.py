"""Config-as-code: agent and permission profiles from TOML (REQ-14).

Loads named agent definitions and permission profiles from .guild/agents.toml
and .guild/permissions.toml respectively.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 - used at runtime in function bodies
from typing import TYPE_CHECKING, Any

from guild.config.constants import AGENTS_FILENAME, DEFAULT_MAX_TURNS, PERMISSIONS_FILENAME
from guild.permissions.checker import PermissionTier
from logger_python import get_logger

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.config.models import GuildConfig

__all__ = [
    "AGENTS_FILENAME",
    "AgentProfile",
    "PERMISSIONS_FILENAME",
    "PermissionProfile",
    "load_agent_profiles",
    "load_permission_profiles",
    "validate_config",
]

logger = get_logger(__name__)


@dataclass
class AgentProfile:
    """A named agent configuration loaded from agents.toml."""

    name: str
    model: str | None = None
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    permission: str = PermissionTier.ASK
    max_turns: int = DEFAULT_MAX_TURNS
    token_budget: int = 0


@dataclass
class PermissionProfile:
    """A named permission configuration loaded from permissions.toml."""

    name: str
    tier: str
    allowed_paths: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)


def load_agent_profiles(guild_dir: Path) -> dict[str, AgentProfile]:
    """Load agent profiles from .guild/agents.toml.

    Each top-level key in the TOML is a profile name. Returns
    a dict mapping profile name to AgentProfile.
    """
    agents_file = guild_dir / AGENTS_FILENAME
    data = _load_toml(agents_file)
    if not data:
        return {}

    profiles: dict[str, AgentProfile] = {}
    for name, values in data.items():
        if not isinstance(values, dict):
            continue
        profiles[name] = _parse_agent_profile(name, values)
    return profiles


def load_permission_profiles(guild_dir: Path) -> dict[str, PermissionProfile]:
    """Load permission profiles from .guild/permissions.toml.

    Each top-level key in the TOML is a profile name. Returns
    a dict mapping profile name to PermissionProfile.
    """
    perms_file = guild_dir / PERMISSIONS_FILENAME
    data = _load_toml(perms_file)
    if not data:
        return {}

    profiles: dict[str, PermissionProfile] = {}
    for name, values in data.items():
        if not isinstance(values, dict):
            continue
        profiles[name] = _parse_permission_profile(name, values)
    return profiles


def _validate_escalation_chain(
    config: GuildConfig,
    known_models: list[str] | None,
    errors: list[str],
) -> None:
    """Check escalation chain model names against known models."""
    if not config.escalation_chain or known_models is None:
        return
    chain_models = [m.strip() for m in config.escalation_chain.split(",") if m.strip()]
    for model_name in chain_models:
        if model_name not in known_models:
            warning = f"Unknown model in escalation chain: '{model_name}'"
            errors.append(warning)
            logger.warning(warning)


def validate_config(
    config: GuildConfig,
    guild_dir: Path,
    known_models: list[str] | None = None,
) -> list[str]:
    """Validate config on startup. Returns list of errors (empty = valid).

    Checks:
    - guild_dir exists
    - model name is non-empty
    - base_url is non-empty
    - max_concurrent_agents > 0
    - agent profile references valid permissions
    - escalation chain model names are known (if known_models provided)
    """
    errors: list[str] = []

    if not guild_dir.is_dir():
        errors.append(f"Guild directory does not exist: {guild_dir}")
        return errors

    if not config.model:
        errors.append("No model specified in config")

    if not config.base_url:
        errors.append("No base_url specified in config")

    if config.max_concurrent_agents < 1:
        errors.append("max_concurrent_agents must be >= 1")

    if config.max_tokens < 1:
        errors.append("max_tokens must be >= 1")

    agent_profiles = load_agent_profiles(guild_dir)
    valid_tiers = {tier.value for tier in PermissionTier}
    for name, profile in agent_profiles.items():
        if profile.permission not in valid_tiers:
            errors.append(
                f"Agent profile '{name}' has invalid permission: " f"'{profile.permission}'"
            )

    _validate_escalation_chain(config, known_models, errors)

    return errors


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on failure or missing file."""
    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.debug("Failed to load %s", path, exc_info=True)
        return {}


def _parse_agent_profile(name: str, values: dict[str, Any]) -> AgentProfile:
    """Parse a dict of TOML values into an AgentProfile."""
    return AgentProfile(
        name=name,
        model=values.get("model"),
        system_prompt=values.get("system_prompt", ""),
        tools=values.get("tools", []),
        permission=values.get("permission", PermissionTier.ASK),
        max_turns=values.get("max_turns", DEFAULT_MAX_TURNS),
        token_budget=values.get("token_budget", 0),
    )


def _parse_permission_profile(name: str, values: dict[str, Any]) -> PermissionProfile:
    """Parse a dict of TOML values into a PermissionProfile."""
    return PermissionProfile(
        name=name,
        tier=values.get("tier", PermissionTier.ASK),
        allowed_paths=values.get("allowed_paths", []),
        allowed_tools=values.get("allowed_tools", []),
    )
