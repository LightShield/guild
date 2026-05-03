"""Tests for CLI commands — init, status, blocks, teams."""

import pytest
from pathlib import Path
from typer.testing import CliRunner

from guild.cli.main import app

runner = CliRunner()


class TestInit:
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


class TestStatus:
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


class TestBlocks:
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


class TestTeams:
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
    def test_empty_learnings(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["learnings"])
        assert result.exit_code == 0
        assert "No learnings" in result.stdout
