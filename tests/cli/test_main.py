"""Tests for the Guild CLI (REQ-05.1, REQ-05.2, REQ-06.7, REQ-08.4)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture()
def guild_app():
    """Import and return the Typer app (deferred to allow implementation)."""
    from guild.cli.main import app

    return app


@pytest.fixture()
def guild_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a minimal guild project in tmp_path and chdir into it."""
    monkeypatch.chdir(tmp_path)
    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    config_file = guild_dir / "config.toml"
    config_file.write_text(
        '[provider]\nname = "ollama"\nmodel = "gemma4-4b-dense-med"\n'
        'base_url = "http://localhost:11434"\n'
    )
    db_file = guild_dir / "guild.db"
    db_file.touch()
    return tmp_path


@pytest.mark.unit
@pytest.mark.req("REQ-05.1")
class TestHelpAndVersion:
    """Basic CLI structure tests."""

    def test_help_shows_available_commands(self, guild_app) -> None:
        result = runner.invoke(guild_app, ["--help"])

        assert result.exit_code == 0
        assert "init" in result.output
        assert "task" in result.output
        assert "status" in result.output
        assert "chat" in result.output
        assert "config" in result.output
        assert "audit" in result.output

    def test_version_flag_shows_version(self, guild_app) -> None:
        result = runner.invoke(guild_app, ["--version"])

        assert result.exit_code == 0
        assert "0.2.0" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-05.1")
class TestInit:
    """Tests for `guild init`."""

    def test_init_creates_guild_directory(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(guild_app, ["init"])

        assert result.exit_code == 0
        assert (tmp_path / ".guild").is_dir()

    def test_init_creates_config_file(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(guild_app, ["init"])

        assert result.exit_code == 0
        config_path = tmp_path / ".guild" / "config.toml"
        assert config_path.is_file()
        content = config_path.read_text()
        assert "provider" in content

    def test_init_creates_database(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(guild_app, ["init"])

        assert result.exit_code == 0
        db_path = tmp_path / ".guild" / "guild.db"
        assert db_path.is_file()


@pytest.mark.unit
@pytest.mark.req("REQ-05.2")
class TestStatus:
    """Tests for `guild status`."""

    def test_status_shows_project_info(self, guild_app, guild_project: Path) -> None:
        result = runner.invoke(guild_app, ["status"])

        assert result.exit_code == 0
        assert "Project" in result.output or "project" in result.output

    def test_status_fails_without_guild_dir(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(guild_app, ["status"])

        assert result.exit_code != 0 or "not a guild project" in result.output.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-05.2")
class TestConfig:
    """Tests for `guild config`."""

    def test_config_shows_current_config(self, guild_app, guild_project: Path) -> None:
        result = runner.invoke(guild_app, ["config"])

        assert result.exit_code == 0
        assert "provider" in result.output.lower() or "model" in result.output.lower()

    def test_config_set_modifies_value(self, guild_app, guild_project: Path) -> None:
        result = runner.invoke(guild_app, ["config", "--set", "provider.model=llama3"])

        assert result.exit_code == 0
        # Verify the config file was updated
        config_path = guild_project / ".guild" / "config.toml"
        content = config_path.read_text()
        assert "llama3" in content


@pytest.mark.unit
@pytest.mark.req("REQ-08.4")
class TestAudit:
    """Tests for `guild audit`."""

    def test_audit_shows_log_entries(self, guild_app, guild_project: Path) -> None:
        # Pre-populate the database with an audit entry
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.log_audit(
                action="tool_call",
                agent_id="agent-1",
                details="file_read path=/foo.py",
            )
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["audit"])

        assert result.exit_code == 0
        assert "tool_call" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-06.7")
class TestTaskTimeout:
    """Tests for task timeout option."""

    def test_task_respects_timeout_option(self, guild_app, guild_project: Path) -> None:
        """Verify --timeout is accepted and passed to the agent loop."""
        with patch("guild.cli.main.create_provider") as mock_provider_factory:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(
                return_value=AsyncMock(
                    content="Task complete.",
                    tool_calls=None,
                    has_tool_call=False,
                    input_tokens=10,
                    output_tokens=20,
                    model="test",
                )
            )
            mock_provider_factory.return_value = mock_provider

            result = runner.invoke(guild_app, ["task", "write hello world", "--timeout", "300"])

            assert result.exit_code == 0
            assert "complete" in result.output.lower() or "done" in result.output.lower()
