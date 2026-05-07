"""Configuration models for Guild (REQ-01.3).

Pydantic models for provider and guild-level configuration,
loaded from TOML files.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from guild.permissions.checker import PermissionTier

__all__ = ["GuildConfig", "ProviderConfig"]


class ProviderConfig(BaseModel):
    """LLM provider settings."""

    name: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "gemma4-4b-dense-med"
    temperature: float = 0.7
    max_tokens: int = 4096


class GuildConfig(BaseModel):
    """Top-level guild configuration."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    default_permission: PermissionTier = PermissionTier.ASK
    max_concurrent_agents: int = 1
    max_concurrent_tool_calls: int = 4
    autonomy_timeout_minutes: int | None = None
    stuck_max_repeated_errors: int = 3
    stuck_max_no_progress_turns: int = 10
    stuck_max_repeated_calls: int = 3
