"""Configuration models for Guild (REQ-01.3).

ConfigsLoader-based declarative config with CLI flags, env vars,
and TOML file support.
"""

from __future__ import annotations

from configsloader import ConfigsLoader, Field

from guild.daemon.resource import SchedulingMode
from guild.permissions.checker import PermissionTier

__all__ = ["GuildConfig"]


class GuildConfig(ConfigsLoader):
    """Unified Guild configuration — flat fields with section-based TOML layout."""

    # Provider section
    provider_name: str = Field(
        default="ollama", section="provider", description="LLM provider name"
    )
    base_url: str = Field(
        default="http://localhost:11434",
        section="provider",
        env="GUILD_BASE_URL",
        description="Provider base URL",
    )
    model: str = Field(
        default="gemma4-4b-dense-med",
        section="provider",
        flags=["--model", "-m"],
        env="GUILD_MODEL",
        description="Model name",
    )
    temperature: float = Field(default=0.7, section="provider", description="Sampling temperature")
    max_tokens: int = Field(default=4096, section="provider", description="Max output tokens")

    # Guild section
    default_permission: PermissionTier = Field(
        default=PermissionTier.ASK,
        section="guild",
        flags=["--permission", "-p"],
        description="Default permission tier",
    )
    max_concurrent_agents: int = Field(
        default=1, section="guild", description="Max concurrent agents"
    )
    max_concurrent_tool_calls: int = Field(
        default=4, section="guild", description="Max concurrent tool calls"
    )
    autonomy_timeout_minutes: int = Field(
        default=0, section="guild", description="Autonomy timeout in minutes (0=unlimited)"
    )

    # Stuck detection (guild section)
    stuck_max_repeated_errors: int = Field(
        default=3, section="guild", description="Max repeated errors before stuck"
    )
    stuck_max_no_progress_turns: int = Field(
        default=10, section="guild", description="Max turns without progress"
    )
    stuck_max_repeated_calls: int = Field(
        default=3, section="guild", description="Max repeated identical calls"
    )

    # Escalation section (REQ-17.7)
    escalation_chain: str = Field(
        default="",
        section="escalation",
        env="GUILD_ESCALATION_CHAIN",
        description="Comma-separated model list for escalation fallback chain",
    )
    escalation_cli_providers: str = Field(
        default="",
        section="escalation",
        env="GUILD_ESCALATION_CLI_PROVIDERS",
        description="Comma-separated CLI tool names to use as last-resort providers",
    )

    # Resource section
    resource_mode: SchedulingMode = Field(
        default=SchedulingMode.POLITE,
        section="resource",
        description="Resource scheduling mode",
    )
