"""Tests for configurable stuck thresholds (D-10 fix)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.config import load_config
from guild.core.models import GuildConfig


class TestConfigurableStuckThresholds:
    """D-10: Stuck thresholds configurable via config.toml."""

    def test_default_thresholds(self):
        config = GuildConfig()
        assert config.stuck_max_repeated_errors == 3
        assert config.stuck_max_no_progress_turns == 10
        assert config.stuck_max_repeated_calls == 3

    def test_thresholds_from_config(self, tmp_path):
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text("""
[guild]
stuck_max_repeated_errors = 5
stuck_max_no_progress_turns = 20
stuck_max_repeated_calls = 7
""")
        config = load_config(guild_dir)
        assert config.stuck_max_repeated_errors == 5
        assert config.stuck_max_no_progress_turns == 20
        assert config.stuck_max_repeated_calls == 7

    def test_partial_override(self, tmp_path):
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text("""
[guild]
stuck_max_repeated_errors = 10
""")
        config = load_config(guild_dir)
        assert config.stuck_max_repeated_errors == 10
        assert config.stuck_max_no_progress_turns == 10  # default
        assert config.stuck_max_repeated_calls == 3  # default
