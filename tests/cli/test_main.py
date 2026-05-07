"""Tests for the Guild CLI (REQ-05.1, REQ-05.2, REQ-06.7, REQ-08.4, REQ-23, REQ-25)."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

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


# ------------------------------------------------------------------
# Daemon / background CLI commands (Milestone 3, Step 15)
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-23.1")
class TestTaskBackgroundFlag:
    """Tests for `guild task --background`."""

    def test_task_background_flag_exists(self, guild_app, guild_project: Path) -> None:
        """Verify --background/-b flag is accepted and launches in background."""
        with patch("guild.cli.main.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            with patch("guild.cli.main._create_task_in_storage", return_value="task-abc"):
                result = runner.invoke(guild_app, ["task", "build the feature", "--background"])

            assert result.exit_code == 0
            assert "task-abc" in result.output or "background" in result.output.lower()
            mock_popen.assert_called_once()


@pytest.mark.unit
@pytest.mark.req("REQ-23.5")
class TestPsCommand:
    """Tests for `guild ps`."""

    def test_ps_command_shows_running_tasks(self, guild_app, guild_project: Path) -> None:
        """Verify ps shows running task information."""
        run_dir = guild_project / ".guild" / "run"
        run_dir.mkdir(parents=True)
        pid_file = run_dir / "task-123.pid"
        pid_file.write_text(str(os.getpid()))  # Use own PID so it appears alive

        result = runner.invoke(guild_app, ["ps"])

        assert result.exit_code == 0
        assert "task-123" in result.output
        assert str(os.getpid()) in result.output

    def test_ps_shows_nothing_when_empty(self, guild_app, guild_project: Path) -> None:
        """Verify ps shows no-tasks message when nothing is running."""
        run_dir = guild_project / ".guild" / "run"
        run_dir.mkdir(parents=True)

        result = runner.invoke(guild_app, ["ps"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "empty" in result.output.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-23.4")
class TestLogsCommand:
    """Tests for `guild logs`."""

    def test_logs_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify logs command is registered and accepts task_id."""
        # Logs with a non-existent task should still not crash
        result = runner.invoke(guild_app, ["logs", "task-nonexistent"])

        assert result.exit_code == 0 or result.exit_code == 1
        # Should either show "no messages" or "task not found" — not a usage error
        assert "Usage" not in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-23.3")
class TestAttachCommand:
    """Tests for `guild attach`."""

    def test_attach_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify attach command is registered."""
        result = runner.invoke(guild_app, ["attach", "task-nonexistent"])

        assert result.exit_code == 0 or result.exit_code == 1
        assert "Usage" not in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-25.1")
class TestKillCommand:
    """Tests for `guild kill`."""

    def test_kill_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify kill command sends graceful shutdown."""
        with patch("guild.cli.main._kill_task") as mock_kill:
            mock_kill.return_value = True

            result = runner.invoke(guild_app, ["kill", "task-123"])

            assert result.exit_code == 0
            mock_kill.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
@pytest.mark.req("REQ-25.2")
class TestPauseCommand:
    """Tests for `guild pause`."""

    def test_pause_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify pause command is registered and calls lifecycle."""
        with patch("guild.cli.main._pause_task") as mock_pause:
            mock_pause.return_value = True

            result = runner.invoke(guild_app, ["pause", "task-123"])

            assert result.exit_code == 0
            mock_pause.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
@pytest.mark.req("REQ-25.3")
class TestResumeCommand:
    """Tests for `guild resume`."""

    def test_resume_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify resume command is registered and calls lifecycle."""
        with patch("guild.cli.main._resume_task") as mock_resume:
            mock_resume.return_value = True

            result = runner.invoke(guild_app, ["resume", "task-123"])

            assert result.exit_code == 0
            mock_resume.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
@pytest.mark.req("REQ-06.12")
class TestDecisionsCommand:
    """Tests for `guild decisions`."""

    def test_decisions_command_shows_entries(self, guild_app, guild_project: Path) -> None:
        """Verify decisions command displays logged decisions."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.log_decision(
                task_id="task-1",
                agent_id="agent-1",
                decision="Use Typer for CLI",
                rationale="Excellent type annotation support",
                alternatives=["click", "argparse"],
            )
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["decisions"], terminal_width=200)

        assert result.exit_code == 0
        assert "Typer" in result.output
        assert "Decision Log" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-06.9")
class TestChatMultiTurn:
    """Tests for multi-turn chat (REQ-06.9)."""

    def test_chat_reuses_agent_loop_across_turns(self, guild_app, guild_project: Path) -> None:
        """Verify chat keeps one AgentLoop and uses send() for follow-ups."""
        mock_response = AsyncMock(
            content="Got it.",
            tool_calls=None,
            has_tool_call=False,
            input_tokens=10,
            output_tokens=20,
            model="test",
        )

        with patch("guild.cli.main.create_provider") as mock_pf:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_pf.return_value = mock_provider

            # Simulate two inputs then Ctrl+C (EOFError)
            result = runner.invoke(
                guild_app,
                ["chat"],
                input="hello\nworld\n",
            )

        assert result.exit_code == 0
        # Provider's generate was called at least twice (once per turn)
        assert mock_provider.generate.call_count >= 2

        # On the second call, the messages should include the first exchange
        second_call_messages = mock_provider.generate.call_args_list[1][0][0]
        roles = [m["role"] for m in second_call_messages]
        # Second call should include: system, user, assistant, user
        assert roles.count("user") == 2
        assert roles.count("assistant") >= 1


@pytest.mark.unit
@pytest.mark.req("REQ-25.8")
class TestKillAllFlag:
    """Tests for `guild kill --all`."""

    def test_kill_all_flag_exists(self, guild_app, guild_project: Path) -> None:
        """Verify kill --all stops all running tasks."""
        with patch("guild.cli.main._kill_all_tasks") as mock_kill_all:
            mock_kill_all.return_value = 3

            result = runner.invoke(guild_app, ["kill", "--all"])

            assert result.exit_code == 0
            mock_kill_all.assert_called_once_with(guild_project / ".guild")
            assert "3" in result.output
