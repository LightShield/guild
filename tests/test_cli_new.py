"""Tests for new CLI commands: templates, artifacts, RPG mode."""

import pytest

pytestmark = pytest.mark.integration

from typer.testing import CliRunner
from guild.cli.main import app

runner = CliRunner()


class TestTemplatesCLI:
    def test_templates_empty(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["templates"])
        assert result.exit_code == 0
        assert "No templates" in result.stdout

    def test_templates_list(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".guild" / "templates" / "dev.toml").write_text("""
[template]
name = "dev"
description = "Dev workflow"
team = "dev-loop"
task_template = "Build {feature}"
parameters = ["feature"]
""")
        result = runner.invoke(app, ["templates"])
        assert "dev" in result.stdout

    def test_template_detail(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".guild" / "templates" / "review.toml").write_text("""
[template]
name = "review"
description = "Code review"
task_template = "Review the code"
""")
        result = runner.invoke(app, ["templates", "review"])
        assert "review" in result.stdout
        assert "Code review" in result.stdout


class TestArtifactsCLI:
    def test_artifacts_empty(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["artifacts"])
        assert result.exit_code == 0
        assert "No artifacts" in result.stdout


class TestRPGMode:
    def test_rpg_flag_exists(self):
        result = runner.invoke(app, ["--help"])
        assert "rpg" in result.stdout.lower()

    def test_blocks_with_rpg(self):
        result = runner.invoke(app, ["--rpg", "blocks"])
        assert result.exit_code == 0
