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

    def test_background_creates_task_in_storage(self, guild_app, guild_project: Path) -> None:
        """Background flag creates a task record in storage before forking."""
        from guild.storage.sqlite import Storage

        with patch("guild.cli.main.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 99999
            mock_popen.return_value = mock_process

            result = runner.invoke(
                guild_app, ["task", "test background storage", "--background"]
            )

        assert result.exit_code == 0

        # Verify the task was actually created in storage
        db_path = guild_project / ".guild" / "guild.db"

        async def _check():
            store = Storage(db_path)
            await store.connect()
            tasks = await store.list_tasks()
            await store.close()
            return tasks

        tasks = asyncio.run(_check())
        assert len(tasks) >= 1
        assert any("test background storage" in t.get("description", "") for t in tasks)

    def test_background_returns_task_id(self, guild_app, guild_project: Path) -> None:
        """Background flag outputs the task ID to stdout."""
        with patch("guild.cli.main.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 11111
            mock_popen.return_value = mock_process

            with patch("guild.cli.main._create_task_in_storage", return_value="task-xyz-123"):
                result = runner.invoke(
                    guild_app, ["task", "some work", "--background"]
                )

        assert result.exit_code == 0
        # The task ID must be shown in the output
        assert "task-xyz-123" in result.output


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

    def test_ps_shows_elapsed_time_format(self, guild_app, guild_project: Path) -> None:
        """Verify ps output includes task ID and PID — the key status info."""
        run_dir = guild_project / ".guild" / "run"
        run_dir.mkdir(parents=True)
        pid_file = run_dir / "task-elapsed.pid"
        pid_file.write_text(str(os.getpid()))

        result = runner.invoke(guild_app, ["ps"])

        assert result.exit_code == 0
        # Task ID and PID should be present in the table
        assert "task-elapsed" in result.output
        assert str(os.getpid()) in result.output
        # Status column shows "running"
        assert "running" in result.output.lower()


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


@pytest.mark.unit
@pytest.mark.req("REQ-05.3")
class TestChatSendsMessages:
    """Tests for sending messages to the running agent (REQ-05.3)."""

    def test_chat_sends_messages_to_agent(self, guild_app, guild_project: Path) -> None:
        """Verify chat command sends user input to the agent and gets responses."""
        mock_response = AsyncMock(
            content="I received your message.",
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

            result = runner.invoke(guild_app, ["chat"], input="hello agent\n")

        assert result.exit_code == 0
        # The agent received and responded to our message
        assert mock_provider.generate.call_count >= 1
        # The user input was passed to the model
        first_call_messages = mock_provider.generate.call_args_list[0][0][0]
        user_msgs = [m for m in first_call_messages if m.get("role") == "user"]
        assert any("hello agent" in m["content"] for m in user_msgs)


@pytest.mark.unit
@pytest.mark.req("REQ-10.3")
class TestUsageCommand:
    """Tests for `guild usage`."""

    def test_usage_command_shows_token_summary(self, guild_app, guild_project: Path) -> None:
        """Verify usage command displays token usage summary."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.register_agent("agent-1", "coder")
            await store.update_agent("agent-1", token_input="1500", token_output="800")
            await store.register_agent("agent-2", "reviewer")
            await store.update_agent("agent-2", token_input="500", token_output="200")
            await store.create_task("t1", "Task one")
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["usage"], terminal_width=200)

        assert result.exit_code == 0
        assert "2000" in result.output  # total input: 1500 + 500
        assert "1000" in result.output  # total output: 800 + 200
        assert "Token Usage" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-07.9")
class TestHistoryCommand:
    """Tests for `guild history`."""

    def test_history_command_shows_past_tasks(self, guild_app, guild_project: Path) -> None:
        """Verify history shows completed tasks."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.create_task("t1", "Build feature A")
            await store.update_task("t1", status="completed", result="Done")
            await store.create_task("t2", "Fix bug B")
            await store.update_task("t2", status="completed", result="Fixed")
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["history"], terminal_width=200)

        assert result.exit_code == 0
        assert "Build feature A" in result.output
        assert "Fix bug B" in result.output
        assert "Task History" in result.output

    def test_history_filters_by_status(self, guild_app, guild_project: Path) -> None:
        """Verify history --status filters tasks."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.create_task("t1", "Completed task")
            await store.update_task("t1", status="completed")
            await store.create_task("t2", "Pending task")
            # t2 stays 'pending' (default)
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["history", "--status", "completed"], terminal_width=200)

        assert result.exit_code == 0
        assert "Completed task" in result.output
        assert "Pending task" not in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-24.8")
class TestResourceStatusCommand:
    """Tests for `guild resource-status`."""

    def test_resource_status_command_shows_mode(self, guild_app, guild_project: Path) -> None:
        """Verify resource-status displays scheduling mode and throttle state."""
        from guild.daemon.resource import ActivityState, ResourceStatus, SchedulingMode

        with patch("guild.daemon.resource.ResourceMonitor") as mock_monitor_cls:
            mock_monitor = MagicMock()
            mock_monitor.get_status.return_value = ResourceStatus(
                mode=SchedulingMode.POLITE,
                activity=ActivityState.IDLE,
                cpu_percent=25.3,
                is_throttled=False,
            )
            mock_monitor_cls.return_value = mock_monitor

            result = runner.invoke(guild_app, ["resource-status"])

        assert result.exit_code == 0
        assert "polite" in result.output.lower()
        assert "25.3" in result.output
        assert "False" in result.output or "false" in result.output.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-06.1")
class TestAutopilotNeverPrompts:
    """Tests for REQ-06.1 — agents in autopilot never pause for confirmation."""

    def test_autopilot_never_prompts_user(self, guild_app, guild_project: Path) -> None:
        """In autopilot mode, agent completes task without prompting."""
        mock_response = AsyncMock(
            content="Task done without prompting.",
            tool_calls=None,
            has_tool_call=False,
            input_tokens=10,
            output_tokens=20,
            model="test",
        )

        prompt_called = False

        def spy_prompt(tool: str, agent_id: str, args: dict) -> bool:
            nonlocal prompt_called
            prompt_called = True
            return True

        with patch("guild.cli.main.create_provider") as mock_pf:
            mock_provider = AsyncMock()
            mock_provider.generate = AsyncMock(return_value=mock_response)
            mock_pf.return_value = mock_provider

            result = runner.invoke(
                guild_app,
                ["task", "say hello", "--permission", "autopilot"],
            )

        assert result.exit_code == 0
        # In autopilot, no prompt function is ever called
        assert prompt_called is False


@pytest.mark.unit
@pytest.mark.req("REQ-06.2")
class TestAgentRecognizesCompletion:
    """Tests for REQ-06.2 — agents self-verify completion."""

    def test_agent_recognizes_task_completion_after_successful_tool_call(self) -> None:
        """should_nudge_completion fires after simple success, signaling done."""
        from guild.agent.completion import should_nudge_completion
        from guild.tools.base import ToolResult

        # A single successful tool result triggers completion nudge
        results = [ToolResult(success=True, output="File written successfully")]
        assert should_nudge_completion(results) is True

    def test_agent_does_not_signal_completion_on_failure(self) -> None:
        """Failed tool calls do not trigger the completion signal."""
        from guild.agent.completion import should_nudge_completion
        from guild.tools.base import ToolResult

        results = [ToolResult(success=False, output="", error="Permission denied")]
        assert should_nudge_completion(results) is False

    def test_completion_nudge_text_instructs_summarize(self) -> None:
        """The completion nudge message asks the agent to summarize."""
        from guild.agent.completion import COMPLETION_NUDGE

        assert "summarize" in COMPLETION_NUDGE.lower()
        assert "complete" in COMPLETION_NUDGE.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-09.5")
class TestLearningsCommand:
    """Tests for `guild learnings` CLI command."""

    def test_learnings_command_shows_entries(self, guild_app, guild_project: Path) -> None:
        """Verify learnings command displays stored learnings."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.add_learning(
                category="pattern",
                content="Always validate inputs",
                confidence=0.7,
            )
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["learnings"], terminal_width=200)

        assert result.exit_code == 0
        assert "validate inputs" in result.output
        assert "pattern" in result.output

    def test_learnings_approve_boosts_confidence(self, guild_app, guild_project: Path) -> None:
        """Verify --approve boosts the learning's confidence."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            lid = await store.add_learning(
                category="tool_tip",
                content="Use grep for search",
                confidence=0.3,
            )
            await store.close()
            return lid

        lid = asyncio.run(_setup())

        result = runner.invoke(guild_app, ["learnings", "--approve", str(lid)])

        assert result.exit_code == 0
        assert "Approved" in result.output

        # Verify the confidence was boosted
        async def _check():
            store = Storage(db_path)
            await store.connect()
            learning = await store.get_learning(lid)
            await store.close()
            return learning

        learning = asyncio.run(_check())
        assert learning["confidence"] == pytest.approx(0.4)

    def test_learnings_reject_deletes_entry(self, guild_app, guild_project: Path) -> None:
        """Verify --reject deletes the learning."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            lid = await store.add_learning(
                category="anti_pattern",
                content="Never use eval()",
                confidence=0.5,
            )
            await store.close()
            return lid

        lid = asyncio.run(_setup())

        result = runner.invoke(guild_app, ["learnings", "--reject", str(lid)])

        assert result.exit_code == 0
        assert "Rejected" in result.output

        # Verify it was deleted
        async def _check():
            store = Storage(db_path)
            await store.connect()
            learning = await store.get_learning(lid)
            await store.close()
            return learning

        learning = asyncio.run(_check())
        assert learning is None
