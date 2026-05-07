"""Tests for config models (REQ-01.3)."""

from __future__ import annotations

import pytest

from guild.config.models import GuildConfig
from guild.daemon.resource import SchedulingMode
from guild.permissions.checker import PermissionTier


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestGuildConfigDefaults:
    """Tests for GuildConfig default values."""

    def test_provider_defaults(self) -> None:
        cfg = GuildConfig()

        assert cfg.provider_name == "ollama"
        assert cfg.base_url == "http://localhost:11434"
        assert cfg.model == "gemma4-4b-dense-med"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_guild_section_defaults(self) -> None:
        cfg = GuildConfig()

        assert cfg.default_permission == PermissionTier.ASK
        assert cfg.max_concurrent_agents == 1
        assert cfg.max_concurrent_tool_calls == 4
        assert cfg.autonomy_timeout_minutes == 0
        assert cfg.stuck_max_repeated_errors == 3
        assert cfg.stuck_max_no_progress_turns == 10
        assert cfg.stuck_max_repeated_calls == 3

    def test_resource_section_defaults(self) -> None:
        cfg = GuildConfig()

        assert cfg.resource_mode == SchedulingMode.POLITE


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestGuildConfigCustomValues:
    """Tests for GuildConfig with custom values."""

    def test_custom_provider_values(self) -> None:
        cfg = GuildConfig(
            provider_name="openai",
            base_url="http://example.com",
            temperature=0.5,
        )

        assert cfg.provider_name == "openai"
        assert cfg.base_url == "http://example.com"
        assert cfg.temperature == 0.5

    def test_permission_tier_accepts_enum(self) -> None:
        cfg = GuildConfig(default_permission=PermissionTier.AUTOPILOT)

        assert cfg.default_permission == PermissionTier.AUTOPILOT

    def test_type_coercion_from_string(self) -> None:
        """ConfigsLoader coerces string values to target types."""
        cfg = GuildConfig(temperature=0.9, max_tokens=8192)

        assert cfg.temperature == 0.9
        assert cfg.max_tokens == 8192
