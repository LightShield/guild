"""Tests for remaining P0 features: health check, safety rules, config CLI, learning validation."""

import asyncio

import pytest

pytestmark = pytest.mark.integration

from typer.testing import CliRunner

from guild.cli.main import app

runner = CliRunner()


class TestConfigCLI:
    """REQ-14: guild config show/set commands."""

    def test_config_show(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "ollama" in result.stdout
        assert "llama3.2" in result.stdout

    def test_config_set(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["config", "--set", "provider.model=codellama"])
        assert result.exit_code == 0

        # Verify it was saved
        import tomllib
        with open(tmp_path / ".guild" / "config.toml", "rb") as f:
            config = tomllib.load(f)
        assert config["provider"]["model"] == "codellama"
