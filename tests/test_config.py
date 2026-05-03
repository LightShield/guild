"""Tests for core/config.py — TOML loading, global/project layering."""

import pytest
from pathlib import Path

from guild.core.config import load_config, find_guild_dir, load_toml
from guild.core.models import PermissionTier


class TestFindGuildDir:
    def test_finds_in_current(self, tmp_path):
        (tmp_path / ".guild").mkdir()
        result = find_guild_dir(tmp_path)
        assert result == tmp_path / ".guild"

    def test_finds_in_parent(self, tmp_path):
        (tmp_path / ".guild").mkdir()
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        result = find_guild_dir(child)
        assert result == tmp_path / ".guild"

    def test_returns_none_when_missing(self, tmp_path):
        result = find_guild_dir(tmp_path)
        assert result is None


class TestLoadToml:
    def test_loads_valid_toml(self, tmp_path):
        f = tmp_path / "test.toml"
        f.write_text('[section]\nkey = "value"\n')
        result = load_toml(f)
        assert result == {"section": {"key": "value"}}

    def test_returns_empty_for_missing(self, tmp_path):
        result = load_toml(tmp_path / "nope.toml")
        assert result == {}


class TestLoadConfig:
    def test_defaults_without_config(self):
        config = load_config(None)
        assert config.provider.name == "ollama"
        assert config.provider.model == "llama3.2"
        assert config.default_permission == PermissionTier.ASK

    def test_project_config_overrides(self, tmp_path):
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nmodel = "codellama"\ntemperature = 0.2\n'
        )
        config = load_config(guild_dir)
        assert config.provider.model == "codellama"
        assert config.provider.temperature == 0.2
        # Non-overridden values keep defaults
        assert config.provider.name == "ollama"

    def test_guild_settings(self, tmp_path):
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[guild]\ndefault_permission = "autopilot"\nmax_concurrent_agents = 4\n'
        )
        config = load_config(guild_dir)
        assert config.default_permission == PermissionTier.AUTOPILOT
        assert config.max_concurrent_agents == 4

    def test_entry_agent_override(self, tmp_path):
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[entry_agent]\nmodel = "llama3:70b"\npermission = "autopilot"\n'
        )
        config = load_config(guild_dir)
        assert config.entry_agent.model == "llama3:70b"
        assert config.entry_agent.permission == PermissionTier.AUTOPILOT

    def test_global_and_project_layering(self, tmp_path, monkeypatch):
        # Create a fake global config dir
        global_dir = tmp_path / "global_guild"
        global_dir.mkdir()
        (global_dir / "config.toml").write_text(
            '[provider]\nmodel = "global-model"\ntemperature = 0.5\n'
        )

        # Create project config that overrides model but not temperature
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nmodel = "project-model"\n'
        )

        # Monkeypatch the global dir
        import guild.core.config as config_mod
        monkeypatch.setattr(config_mod, "GLOBAL_DIR", global_dir)

        config = load_config(guild_dir)
        assert config.provider.model == "project-model"  # project wins
        assert config.provider.temperature == 0.5  # from global
