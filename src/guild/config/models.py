"""Configuration models for Guild (REQ-01.3).

ConfigsLoader-based declarative config with CLI flags, env vars,
and TOML file support.
"""

from __future__ import annotations

from configsloader import ConfigsLoader, Field
from guild.config.constants import (
    CLI_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_COMPACT_THRESHOLD,
    DEFAULT_CONTEXT_MAX_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TURNS,
    DEFAULT_PRESERVE_RECENT,
    MAX_SHELL_OUTPUT_CHARS,
    MAX_SPAWN_DEPTH,
    SHELL_TIMEOUT_SECONDS,
    WEBSOCKET_POLL_SECONDS,
)
from guild.daemon.resource import SchedulingMode
from guild.permissions.checker import PermissionTier

__all__ = ["GuildConfig"]


class GuildConfig(ConfigsLoader):  # type: ignore[misc]
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
    max_tokens: int = Field(
        default=DEFAULT_MAX_TOKENS,
        section="provider",
        description="Max output tokens",
    )

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

    # Operational constants (guild section)
    shell_timeout_seconds: int = Field(
        default=SHELL_TIMEOUT_SECONDS,
        section="guild",
        description="Shell command timeout in seconds",
    )
    shell_max_output_chars: int = Field(
        default=MAX_SHELL_OUTPUT_CHARS,
        section="guild",
        description="Max shell output characters before truncation",
    )
    cli_provider_timeout_seconds: int = Field(
        default=CLI_PROVIDER_TIMEOUT_SECONDS,
        section="guild",
        description="CLI provider command timeout in seconds",
    )
    default_max_turns: int = Field(
        default=DEFAULT_MAX_TURNS, section="guild", description="Default max agent loop turns"
    )
    context_max_tokens: int = Field(
        default=DEFAULT_CONTEXT_MAX_TOKENS,
        section="guild",
        description="Max estimated tokens for context window",
    )
    compact_threshold: float = Field(
        default=DEFAULT_COMPACT_THRESHOLD,
        section="guild",
        description="Context token fraction triggering compaction",
    )
    preserve_recent_messages: int = Field(
        default=DEFAULT_PRESERVE_RECENT,
        section="guild",
        description="Recent messages preserved during compaction",
    )
    websocket_poll_seconds: int = Field(
        default=WEBSOCKET_POLL_SECONDS,
        section="guild",
        description="WebSocket status broadcast interval in seconds",
    )

    # Health check (provider section)
    health_check_timeout_seconds: int = Field(
        default=5,
        section="provider",
        description="Health check timeout in seconds",
    )

    # Spawn depth limit (guild section)
    max_spawn_depth: int = Field(
        default=MAX_SPAWN_DEPTH, section="guild", description="Max nested sub-agent spawn depth"
    )

    # Auto-recovery (daemon section)
    auto_recovery: bool = Field(
        default=False, section="daemon", description="Automatically restart crashed agents"
    )

    # Presence-aware notifications (daemon section)
    presence_aware_notifications: bool = Field(
        default=False,
        section="daemon",
        description="Check user presence before dispatching notifications",
    )

    # Security section
    sandbox_mode: str = Field(
        default="auto",
        section="security",
        description="Sandbox mode: auto/docker/none",
    )
    sandbox_network: bool = Field(
        default=False,
        section="security",
        description="Whether sandboxed commands get network access",
    )

    # Routing section (REQ-17.3)
    permission_model: str = Field(
        default="",
        section="routing",
        env="GUILD_PERMISSION_MODEL",
        description="Lightweight model for permission decisions (empty = use main model)",
    )

    # Resource section
    resource_mode: SchedulingMode = Field(
        default=SchedulingMode.POLITE,
        section="resource",
        description="Resource scheduling mode",
    )
