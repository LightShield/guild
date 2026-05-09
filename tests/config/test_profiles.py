"""Tests for config/profiles.py — config-as-code (REQ-14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.config.profiles import (
    AgentProfile,
    PermissionProfile,
    load_agent_profiles,
    load_permission_profiles,
    validate_config,
)


@pytest.mark.unit
@pytest.mark.req("REQ-14.1")
class TestAgentProfiles:
    """Tests for loading agent profiles from TOML."""

    def test_load_agent_profile_from_toml(self, tmp_path: Path) -> None:
        """load_agent_profiles reads agent definitions from agents.toml."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text(
            "[coder]\n"
            'model = "llama3"\n'
            'system_prompt = "You are a coder."\n'
            'tools = ["file_read", "file_write", "shell"]\n'
            'permission = "scoped"\n'
            "max_turns = 30\n"
            "token_budget = 10000\n"
        )

        profiles = load_agent_profiles(guild_dir)

        assert "coder" in profiles
        profile = profiles["coder"]
        assert isinstance(profile, AgentProfile)
        assert profile.name == "coder"
        assert profile.model == "llama3"
        assert profile.system_prompt == "You are a coder."
        assert profile.tools == ["file_read", "file_write", "shell"]
        assert profile.permission == "scoped"
        assert profile.max_turns == 30
        assert profile.token_budget == 10000

    def test_agent_profile_defaults(self, tmp_path: Path) -> None:
        """Agent profiles use sensible defaults for omitted fields."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        # Minimal profile — only name is implicit from key
        agents_toml.write_text('[minimal]\nsystem_prompt = "Hello"\n')

        profiles = load_agent_profiles(guild_dir)

        assert "minimal" in profiles
        profile = profiles["minimal"]
        assert profile.model is None
        assert profile.tools == []
        assert profile.permission == "ask"
        assert profile.max_turns == 50
        assert profile.token_budget == 0

    def test_load_multiple_agent_profiles(self, tmp_path: Path) -> None:
        """Multiple agent profiles are loaded from a single file."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text(
            '[coder]\nmodel = "llama3"\n\n'
            '[reviewer]\nmodel = "mistral"\npermission = "autopilot"\n'
        )

        profiles = load_agent_profiles(guild_dir)

        assert len(profiles) == 2
        assert "coder" in profiles
        assert "reviewer" in profiles
        assert profiles["reviewer"].permission == "autopilot"

    def test_load_agent_profiles_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        """Returns empty dict when agents.toml does not exist."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        profiles = load_agent_profiles(guild_dir)

        assert profiles == {}


@pytest.mark.unit
@pytest.mark.req("REQ-14.3")
class TestPermissionProfiles:
    """Tests for loading permission profiles from TOML."""

    def test_load_permission_profile_from_toml(self, tmp_path: Path) -> None:
        """load_permission_profiles reads permission definitions."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        perms_toml = guild_dir / "permissions.toml"
        perms_toml.write_text(
            "[sandbox]\n" 'tier = "scoped"\n' 'allowed_tools = ["file_read", "search"]\n'
        )

        profiles = load_permission_profiles(guild_dir)

        assert "sandbox" in profiles
        profile = profiles["sandbox"]
        assert isinstance(profile, PermissionProfile)
        assert profile.name == "sandbox"
        assert profile.tier == "scoped"
        assert profile.allowed_tools == ["file_read", "search"]

    def test_permission_profile_with_paths(self, tmp_path: Path) -> None:
        """Permission profiles can restrict allowed filesystem paths."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        perms_toml = guild_dir / "permissions.toml"
        perms_toml.write_text(
            "[restricted]\n"
            'tier = "scoped"\n'
            'allowed_paths = ["/home/user/project", "/tmp"]\n'
            'allowed_tools = ["file_read"]\n'
        )

        profiles = load_permission_profiles(guild_dir)

        profile = profiles["restricted"]
        assert profile.allowed_paths == ["/home/user/project", "/tmp"]
        assert profile.allowed_tools == ["file_read"]

    def test_permission_profile_defaults(self, tmp_path: Path) -> None:
        """Permission profiles default to empty lists for paths and tools."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        perms_toml = guild_dir / "permissions.toml"
        perms_toml.write_text('[basic]\ntier = "ask"\n')

        profiles = load_permission_profiles(guild_dir)

        profile = profiles["basic"]
        assert profile.allowed_paths == []
        assert profile.allowed_tools == []

    def test_load_permission_profiles_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        """Returns empty dict when permissions.toml does not exist."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        profiles = load_permission_profiles(guild_dir)

        assert profiles == {}


@pytest.mark.unit
@pytest.mark.req("REQ-14.5")
class TestConfigValidation:
    """Tests for startup config validation."""

    def test_validate_config_returns_empty_on_valid(self, tmp_path: Path) -> None:
        """Valid config produces no errors."""
        from guild.config.loader import load_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)

        assert errors == []

    def test_validate_config_returns_errors_on_invalid(self, tmp_path: Path) -> None:
        """Invalid config (missing guild_dir) produces errors."""
        from guild.config.loader import load_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = load_config(guild_dir=guild_dir)

        # Validate against a non-existent directory
        fake_dir = tmp_path / "nonexistent"
        errors = validate_config(config, fake_dir)

        assert len(errors) >= 1
        assert any("does not exist" in e for e in errors)

    def test_validate_config_catches_invalid_permission_tier(self, tmp_path: Path) -> None:
        """Agent profiles with invalid permission tiers are flagged."""
        from guild.config.loader import load_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text('[bad_agent]\npermission = "invalid_tier"\n')

        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)

        assert any("invalid permission" in e for e in errors)

    def test_validate_catches_missing_model(self, tmp_path: Path) -> None:
        """Validation catches empty model field as an error."""
        from guild.config.loader import load_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        # Write a config with empty model
        config_toml = guild_dir / "config.toml"
        config_toml.write_text('[provider]\nmodel = ""\nbase_url = "http://localhost:11434"\n')

        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)

        assert any("model" in e.lower() for e in errors)

    def test_validate_catches_invalid_permission(self, tmp_path: Path) -> None:
        """Validation catches multiple agents with different invalid permissions."""
        from guild.config.loader import load_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text(
            '[agent_a]\npermission = "root"\n\n'
            '[agent_b]\npermission = "sudo"\n'
        )

        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)

        # Both invalid permissions should be caught
        permission_errors = [e for e in errors if "invalid permission" in e]
        assert len(permission_errors) == 2
        assert any("agent_a" in e for e in permission_errors)
        assert any("agent_b" in e for e in permission_errors)
