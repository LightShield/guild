"""Tests for CLI commands — init, status, blocks, teams, audit, and new features."""

import asyncio
import json
import tomllib

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path
from typer.testing import CliRunner

from guild.cli.main import app

runner = CliRunner()


class TestInit:
    """REQ-02, AD-01: guild init creates proper project structure."""

    def test_creates_guild_dir(self, tmp_path):
        result = runner.invoke(app, ["init", str(tmp_path / "project")])
        assert result.exit_code == 0
        guild_dir = tmp_path / "project" / ".guild"
        assert guild_dir.is_dir()
        assert (guild_dir / "guild.db").exists()
        assert (guild_dir / "config.toml").exists()
        assert (guild_dir / "blocks").is_dir()
        assert (guild_dir / "learnings").is_dir()
        assert (guild_dir / "artifacts").is_dir()

    def test_idempotent(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert "already exists" in result.stdout

    def test_default_config_has_all_sections(self, tmp_path):
        """Config must have provider, guild sections with documented defaults."""
        runner.invoke(app, ["init", str(tmp_path)])
        config_path = tmp_path / ".guild" / "config.toml"
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        assert "provider" in config
        assert config["provider"]["name"] == "ollama"
        assert config["provider"]["model"] == "llama3.2"
        assert "guild" in config
        assert config["guild"]["default_permission"] == "ask"

    def test_db_has_init_audit_entry(self, tmp_path):
        """DB should log the project_init event."""
        runner.invoke(app, ["init", str(tmp_path)])

        async def _check():
            from guild.core.storage import Storage
            s = Storage(tmp_path / ".guild" / "guild.db")
            await s.connect()
            async with s.db.execute("SELECT * FROM audit_log WHERE action = 'project_init'") as cur:
                rows = await cur.fetchall()
            await s.close()
            return rows

        rows = asyncio.run(_check())
        assert len(rows) == 1


class TestStatus:
    """REQ-05.1: guild status shows project info."""

    def test_shows_project_info(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Guild Project" in result.stdout

    def test_fails_without_init(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1

    def test_shows_learnings_count(self, tmp_path, monkeypatch):
        """REQ-09: Status should show learning count if any exist."""
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)

        async def _add_learning():
            from guild.core.storage import Storage
            s = Storage(tmp_path / ".guild" / "guild.db")
            await s.connect()
            await s.add_learning("pattern", "test insight", confidence=0.9)
            await s.close()

        asyncio.run(_add_learning())
        result = runner.invoke(app, ["status"])
        assert "learning" in result.stdout


class TestBlocks:
    """REQ-04.23: Block listing and details."""

    def test_list_blocks(self):
        result = runner.invoke(app, ["blocks"])
        assert result.exit_code == 0
        assert "coder" in result.stdout
        assert "planner" in result.stdout
        assert "reviewer" in result.stdout

    def test_show_block_detail(self):
        result = runner.invoke(app, ["blocks", "coder"])
        assert result.exit_code == 0
        assert "coder" in result.stdout
        assert "file_write" in result.stdout

    def test_unknown_block(self):
        result = runner.invoke(app, ["blocks", "nonexistent"])
        assert result.exit_code == 1

    def test_custom_block_from_guild_dir(self, tmp_path, monkeypatch):
        """REQ-04.23, REQ-14: Custom blocks from .guild/blocks/ TOML files."""
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        blocks_dir = tmp_path / ".guild" / "blocks"
        (blocks_dir / "my_custom.toml").write_text("""
[block]
name = "my-custom-block"
role = "custom"
system_prompt = "You are custom."
tools = ["file_read"]

[[block.inputs]]
name = "data"
type_tag = "text"

[[block.outputs]]
name = "result"
type_tag = "text"
""")
        result = runner.invoke(app, ["blocks"])
        assert "my-custom" in result.stdout


class TestTeams:
    """REQ-04.9: Team listing and details."""

    def test_list_teams(self):
        result = runner.invoke(app, ["teams"])
        assert result.exit_code == 0
        assert "dev-loop" in result.stdout
        assert "verified-coder" in result.stdout

    def test_show_team_detail(self):
        result = runner.invoke(app, ["teams", "dev-loop"])
        assert result.exit_code == 0
        assert "planner" in result.stdout
        assert "coder" in result.stdout
        assert "Valid" in result.stdout

    def test_unknown_team(self):
        result = runner.invoke(app, ["teams", "nonexistent"])
        assert result.exit_code == 1


class TestLearnings:
    """REQ-09: Learning display."""

    def test_empty_learnings(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["learnings"])
        assert result.exit_code == 0
        assert "No learnings" in result.stdout


class TestAudit:
    """REQ-03.8, REQ-10: Audit log queryable from CLI."""

    def test_audit_shows_events(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        # Should show the project_init event at minimum
        assert "project_init" in result.stdout

    def test_audit_empty_project(self, tmp_path, monkeypatch):
        """Even a fresh project has the init audit entry."""
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0

    def test_audit_limit(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["audit", "--limit", "1"])
        assert result.exit_code == 0
