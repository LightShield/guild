"""Tests for config loader (REQ-01.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.config.loader import find_guild_dir, load_config
from guild.config.models import GuildConfig


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestFindGuildDir:
    """Tests for find_guild_dir."""

    def test_find_guild_dir_finds_in_current(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        result = find_guild_dir(start=tmp_path)

        assert result == guild_dir

    def test_find_guild_dir_finds_in_parent(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        child = tmp_path / "subdir" / "deep"
        child.mkdir(parents=True)

        result = find_guild_dir(start=child)

        assert result == guild_dir

    def test_find_guild_dir_returns_none_when_absent(self, tmp_path: Path) -> None:
        result = find_guild_dir(start=tmp_path)

        assert result is None


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestLoadConfig:
    """Tests for load_config."""

    def test_load_config_uses_defaults_when_no_files(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        cfg = load_config(guild_dir=guild_dir)

        assert isinstance(cfg, GuildConfig)
        assert cfg.provider_name == "ollama"

    def test_load_config_project_overrides_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Set up a fake global config dir
        global_dir = tmp_path / "global" / ".guild"
        global_dir.mkdir(parents=True)
        global_config = global_dir / "config.toml"
        global_config.write_text(
            '[provider]\nprovider_name = "global_provider"\ntemperature = 0.3\n'
        )

        # Set up project config that overrides provider name
        project_dir = tmp_path / "project" / ".guild"
        project_dir.mkdir(parents=True)
        project_config = project_dir / "config.toml"
        project_config.write_text('[provider]\nprovider_name = "project_provider"\n')

        monkeypatch.setenv("HOME", str(tmp_path / "global"))

        cfg = load_config(guild_dir=project_dir)

        assert cfg.provider_name == "project_provider"
        # Global temperature should still be picked up via merge
        assert cfg.temperature == 0.3

    def test_load_config_reads_provider_section(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_file = guild_dir / "config.toml"
        config_file.write_text(
            '[provider]\nprovider_name = "anthropic"\nmodel = "claude-3"\nmax_tokens = 8192\n'
        )

        cfg = load_config(guild_dir=guild_dir)

        assert cfg.provider_name == "anthropic"
        assert cfg.model == "claude-3"
        assert cfg.max_tokens == 8192

    def test_load_config_reads_guild_section(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_file = guild_dir / "config.toml"
        config_file.write_text(
            "[guild]\n"
            "max_concurrent_agents = 4\n"
            'default_permission = "autopilot"\n'
            "stuck_max_repeated_errors = 5\n"
        )

        cfg = load_config(guild_dir=guild_dir)

        assert cfg.max_concurrent_agents == 4
        assert cfg.default_permission.value == "autopilot"
        assert cfg.stuck_max_repeated_errors == 5

    def test_load_config_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        monkeypatch.setenv("GUILD_MODEL", "llama3")

        cfg = load_config(guild_dir=guild_dir)

        assert cfg.model == "llama3"

    def test_load_config_cli_flags(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        cfg = load_config(guild_dir=guild_dir, args=["--model", "mistral"])

        assert cfg.model == "mistral"

    def test_load_config_cli_overrides_file(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_file = guild_dir / "config.toml"
        config_file.write_text('[provider]\nmodel = "from-file"\n')

        cfg = load_config(guild_dir=guild_dir, args=["--model", "from-cli"])

        assert cfg.model == "from-cli"

    def test_load_config_with_resource_section(self, tmp_path: Path) -> None:
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_file = guild_dir / "config.toml"
        config_file.write_text('[resource]\nresource_mode = "stealth"\n')

        cfg = load_config(guild_dir=guild_dir)

        assert cfg.resource_mode.value == "stealth"
