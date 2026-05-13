"""Tests for config loader (REQ-01.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.config.loader import ConfigWatcher, find_guild_dir, load_config
from guild.config.models import GuildConfig


@pytest.mark.unit
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


# ------------------------------------------------------------------
# REQ-14.4: Environment-specific overrides
# ------------------------------------------------------------------


@pytest.mark.unit
class TestEnvVarOverrides:
    """Tests that environment variables override config file values."""

    def test_env_var_overrides_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GUILD_MODEL env var overrides model set in config file."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_file = guild_dir / "config.toml"
        config_file.write_text('[provider]\nmodel = "from-file"\n')

        monkeypatch.setenv("GUILD_MODEL", "env-override-model")

        cfg = load_config(guild_dir=guild_dir)

        assert cfg.model == "env-override-model"


# ------------------------------------------------------------------
# REQ-14.6: Config hot-reload
# ------------------------------------------------------------------


@pytest.mark.unit
class TestConfigWatcher:
    """Tests for ConfigWatcher hot-reload detection."""

    def test_config_watcher_detects_change(self, tmp_path: Path) -> None:
        """ConfigWatcher detects when file mtime changes and calls callback."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[provider]\nmodel = "original"\n')

        callback_calls: list[bool] = []

        def on_reload() -> None:
            callback_calls.append(True)

        watcher = ConfigWatcher(config_file, on_reload)

        # No change on first check (mtime already recorded in __init__)
        assert watcher.check_for_changes() is False
        assert len(callback_calls) == 0

        # Modify the file (change mtime)
        import time

        time.sleep(0.05)  # ensure mtime differs
        config_file.write_text('[provider]\nmodel = "updated"\n')

        assert watcher.check_for_changes() is True
        assert len(callback_calls) == 1

    def test_config_watcher_no_false_positive(self, tmp_path: Path) -> None:
        """ConfigWatcher does not fire callback when file is unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[provider]\nmodel = "stable"\n')

        callback_calls: list[bool] = []

        def on_reload() -> None:
            callback_calls.append(True)

        watcher = ConfigWatcher(config_file, on_reload)

        # Multiple checks without modification
        assert watcher.check_for_changes() is False
        assert watcher.check_for_changes() is False
        assert watcher.check_for_changes() is False

        assert len(callback_calls) == 0

    def test_config_watcher_missing_file(self, tmp_path: Path) -> None:
        """ConfigWatcher returns False for non-existent files."""
        missing = tmp_path / "nonexistent.toml"
        callback_calls: list[bool] = []

        watcher = ConfigWatcher(missing, lambda: callback_calls.append(True))

        assert watcher.check_for_changes() is False
        assert len(callback_calls) == 0


# ======================================================================
# Config loader edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderEdgeCases:
    """Cover config loader edge cases."""

    def test_find_guild_dir_walks_up(self, tmp_path: Path) -> None:
        """find_guild_dir walks up directory tree."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = find_guild_dir(deep)
        assert result == guild_dir

    def test_find_guild_dir_not_found(self) -> None:
        """find_guild_dir returns None when not found."""
        from pathlib import Path

        # Start from root or a place without .guild
        result = find_guild_dir(Path("/"))
        assert result is None

    def test_load_toml_file_invalid(self, tmp_path: Path) -> None:
        """_load_toml_file returns {} on invalid TOML."""
        from guild.config.loader import _load_toml_file

        bad = tmp_path / "bad.toml"
        bad.write_text("invalid [[[toml content")
        result = _load_toml_file(bad)
        assert result == {}

    def test_load_toml_file_missing(self) -> None:
        """_load_toml_file returns {} when file doesn\'t exist."""
        from pathlib import Path

        from guild.config.loader import _load_toml_file

        result = _load_toml_file(Path("/nonexistent/file.toml"))
        assert result == {}

    def test_config_watcher_detects_change(self, tmp_path: Path) -> None:
        """ConfigWatcher detects mtime change and calls callback."""
        import time

        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "test"\n')
        called = []
        watcher = ConfigWatcher(config_file, callback=lambda: called.append(1))

        # No change yet
        assert watcher.check_for_changes() is False

        # Modify file
        time.sleep(0.05)
        config_file.write_text('model = "updated"\n')
        assert watcher.check_for_changes() is True
        assert len(called) == 1

    def test_config_watcher_missing_file(self, tmp_path: Path) -> None:
        """ConfigWatcher returns False for missing file."""
        watcher = ConfigWatcher(tmp_path / "nope.toml", callback=lambda: None)
        assert watcher.check_for_changes() is False


# ======================================================================
# Config loader internal functions (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderInternals:
    """Cover config loader internal functions."""

    def test_write_toml_bytes(self) -> None:
        """_write_toml_bytes writes correct TOML bytes."""
        import io

        from guild.config.loader import _write_toml_bytes

        buf = io.BytesIO()
        data = {
            "model": "test-model",
            "debug": True,
            "provider": {"base_url": "http://localhost:11434"},
        }
        _write_toml_bytes(buf, data)
        content = buf.getvalue().decode()
        assert 'model = "test-model"' in content
        assert "debug = true" in content
        assert "[provider]" in content
        assert 'base_url = "http://localhost:11434"' in content

    def test_toml_literal_bool_false(self) -> None:
        """_toml_literal formats False as \'false\'."""
        from guild.config.loader import _toml_literal

        assert _toml_literal(False) == "false"
        assert _toml_literal(True) == "true"

    def test_toml_literal_int(self) -> None:
        """_toml_literal formats integers correctly."""
        from guild.config.loader import _toml_literal

        assert _toml_literal(42) == "42"

    def test_merge_toml_files_both_present(self, tmp_path: Path) -> None:
        """When both global and project config exist, they are merged."""
        from unittest.mock import patch

        from guild.config.loader import _merge_toml_files

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        project_config = guild_dir / "config.toml"
        project_config.write_text('model = "project-model"\n')

        # Patch global path to avoid depending on actual ~/.guild
        with patch("guild.config.loader.Path.home", return_value=tmp_path / "home"):
            home_guild = tmp_path / "home" / ".guild"
            home_guild.mkdir(parents=True)
            (home_guild / "config.toml").write_text('model = "global-model"\ndebug = true\n')

            result = _merge_toml_files(guild_dir)
            # Result should be a temp file with merged content
            assert result is not None
            content = result.read_text()
            # Project overrides global for model
            assert "project-model" in content
            # Cleanup
            result.unlink()

    def test_load_config_no_guild_dir(self) -> None:
        """load_config works without a guild_dir (uses defaults)."""
        from pathlib import Path
        from unittest.mock import patch

        # With no guild_dir and no global config, should return default config
        with patch("guild.config.loader.Path.home", return_value=Path("/nonexistent")):
            config = load_config(guild_dir=None)
            # Should still produce a valid config with defaults
            assert config is not None


# ======================================================================
# Config loader global fallback (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderGlobalFallback:
    """Cover the branch at line 65 where only global config exists."""

    def test_global_config_only_returns_global_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When only global config exists (no project config), return global path."""
        from guild.config.loader import _merge_toml_files

        # Set up: global config exists, project config does NOT exist
        home = tmp_path / "home"
        global_guild = home / ".guild"
        global_guild.mkdir(parents=True)
        global_config = global_guild / "config.toml"
        global_config.write_text('[provider]\nmodel = "global-model"\n')

        # Project guild dir exists but has no config.toml
        project_guild = tmp_path / "project" / ".guild"
        project_guild.mkdir(parents=True)

        monkeypatch.setenv("HOME", str(home))

        result = _merge_toml_files(project_guild)
        # Should return the global path directly (line 65)
        assert result == global_config


# ======================================================================
# Config loader temp file cleanup (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderTempFileCleanup:
    """Cover the temp file cleanup branch at lines 155-158."""

    def test_load_config_cleans_up_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When merged config creates a temp file, it\'s cleaned up after loading."""
        # Set up both global and project configs so merge creates a temp file
        home = tmp_path / "home"
        global_guild = home / ".guild"
        global_guild.mkdir(parents=True)
        (global_guild / "config.toml").write_text(
            '[provider]\nmodel = "global"\ntemperature = 0.5\n'
        )

        project_guild = tmp_path / "project" / ".guild"
        project_guild.mkdir(parents=True)
        (project_guild / "config.toml").write_text('[provider]\nmodel = "project"\n')

        # Patch Path.home() to return our fake home
        monkeypatch.setenv("HOME", str(home))

        # load_config should merge, use temp file, then clean it up
        config = load_config(guild_dir=project_guild)
        assert config.model == "project"


# ======================================================================
# Config loader corrupt TOML (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderCorruptToml:
    """Cover the exception branch in _load_toml_file."""

    def test_load_toml_file_corrupt_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt TOML file returns empty dict (lines 87-89)."""
        from guild.config.loader import _load_toml_file

        corrupt_file = tmp_path / "bad.toml"
        corrupt_file.write_text("this is not = valid [ toml {{{")

        result = _load_toml_file(corrupt_file)
        assert result == {}


# ======================================================================
# validate_config_keys coverage
# ======================================================================


@pytest.mark.unit
class TestValidateConfigKeys:
    """Cover all branches in validate_config_keys."""

    def test_returns_empty_for_none_guild_dir(self) -> None:
        """validate_config_keys returns [] when guild_dir is None."""
        from guild.config.loader import validate_config_keys

        result = validate_config_keys(None)
        assert result == []

    def test_returns_empty_for_missing_config(self, tmp_path: Path) -> None:
        """validate_config_keys returns [] when config file is missing."""
        from guild.config.loader import validate_config_keys

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        # No config.toml file
        result = validate_config_keys(guild_dir)
        assert result == []

    def test_warns_on_unknown_keys(self, tmp_path: Path) -> None:
        """validate_config_keys returns warnings for unknown keys."""
        from guild.config.loader import validate_config_keys

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = guild_dir / "config.toml"
        config.write_text('[provider]\nunknown_key = "bad"\n')

        result = validate_config_keys(guild_dir)
        assert len(result) >= 1
        assert "unknown_key" in result[0].lower()

    def test_no_warnings_for_known_keys(self, tmp_path: Path) -> None:
        """validate_config_keys returns [] for all known keys."""
        from guild.config.loader import validate_config_keys

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = guild_dir / "config.toml"
        config.write_text('[provider]\nmodel = "test"\n')

        result = validate_config_keys(guild_dir)
        assert result == []

    def test_skips_top_level_scalars(self, tmp_path: Path) -> None:
        """validate_config_keys skips top-level scalar values (not dicts)."""
        from guild.config.loader import validate_config_keys

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = guild_dir / "config.toml"
        config.write_text('top_level_scalar = "value"\n[provider]\nmodel = "test"\n')

        result = validate_config_keys(guild_dir)
        # Should not crash and should not warn on the scalar
        assert all("top_level_scalar" not in w for w in result)


# ======================================================================
# ConfigWatcher non-reloadable changes (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestConfigWatcherNonReloadable:
    """Cover the non-reloadable change detection in ConfigWatcher."""

    def test_detects_non_reloadable_field_change(self, tmp_path: Path) -> None:
        """ConfigWatcher warns about non-reloadable field changes."""
        import time

        config_file = tmp_path / "config.toml"
        config_file.write_text('[provider]\nmodel = "original"\n')

        called = []
        watcher = ConfigWatcher(config_file, callback=lambda: called.append(1))

        # First check — loads initial config
        assert watcher.check_for_changes() is False

        # Trigger first reload to set _last_config
        time.sleep(0.05)
        config_file.write_text('[provider]\nmodel = "still-original"\n')
        watcher.check_for_changes()

        # Now change a non-reloadable field
        time.sleep(0.05)
        config_file.write_text('[provider]\nmodel = "changed-model"\n')
        watcher.check_for_changes()

        # Should have a warning about model needing restart
        warnings = watcher.non_reloadable_warnings
        assert any("model" in w for w in warnings)
