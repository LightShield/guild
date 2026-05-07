"""Tests for config models (REQ-01.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from guild.config.models import GuildConfig, ProviderConfig
from guild.permissions.checker import PermissionTier


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestProviderConfig:
    """Tests for ProviderConfig model."""

    def test_provider_config_defaults(self) -> None:
        cfg = ProviderConfig()

        assert cfg.name == "ollama"
        assert cfg.base_url == "http://localhost:11434"
        assert cfg.model == "gemma4-4b-dense-med"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_provider_config_validates_types(self) -> None:
        cfg = ProviderConfig(name="openai", base_url="http://example.com", temperature=0.5)

        assert cfg.name == "openai"
        assert cfg.base_url == "http://example.com"
        assert cfg.temperature == 0.5

    def test_provider_config_rejects_invalid_temperature(self) -> None:
        with pytest.raises(ValidationError):
            ProviderConfig(temperature="not_a_float")  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestGuildConfig:
    """Tests for GuildConfig model."""

    def test_guild_config_defaults(self) -> None:
        cfg = GuildConfig()

        assert cfg.max_concurrent_agents == 1
        assert cfg.max_concurrent_tool_calls == 4
        assert cfg.autonomy_timeout_minutes is None
        assert cfg.stuck_max_repeated_errors == 3
        assert cfg.stuck_max_no_progress_turns == 10
        assert cfg.stuck_max_repeated_calls == 3

    def test_guild_config_has_provider(self) -> None:
        cfg = GuildConfig()

        assert isinstance(cfg.provider, ProviderConfig)
        assert cfg.provider.name == "ollama"

    def test_guild_config_permission_tier_validates(self) -> None:
        cfg = GuildConfig(default_permission=PermissionTier.AUTOPILOT)
        assert cfg.default_permission == PermissionTier.AUTOPILOT

        with pytest.raises(ValidationError):
            GuildConfig(default_permission="invalid_tier")  # type: ignore[arg-type]
