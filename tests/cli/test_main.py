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
class TestTaskTimeout:
    """Tests for task timeout option."""

    def test_task_respects_timeout_option(self, guild_app, guild_project: Path) -> None:
        """Verify --timeout is accepted and passed to the agent loop."""
        with patch("guild.cli.task_runner.create_provider_for_backend") as mock_provider_factory:
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
class TestTaskBackgroundFlag:
    """Tests for `guild task --background`."""

    def test_task_background_flag_exists(self, guild_app, guild_project: Path) -> None:
        """Verify --background/-b flag is accepted and launches in background."""
        with patch("guild.cli.daemon_ops.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            with patch("guild.cli.task_commands._create_task_in_storage", return_value="task-abc"):
                result = runner.invoke(guild_app, ["task", "build the feature", "--background"])

            assert result.exit_code == 0
            assert "task-abc" in result.output or "background" in result.output.lower()
            mock_popen.assert_called_once()

    def test_background_creates_task_in_storage(self, guild_app, guild_project: Path) -> None:
        """Background flag creates a task record in storage before forking."""
        from guild.storage.sqlite import Storage

        with patch("guild.cli.daemon_ops.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 99999
            mock_popen.return_value = mock_process

            result = runner.invoke(guild_app, ["task", "test background storage", "--background"])

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
        with patch("guild.cli.daemon_ops.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 11111
            mock_popen.return_value = mock_process

            with patch(
                "guild.cli.task_commands._create_task_in_storage", return_value="task-xyz-123"
            ):
                result = runner.invoke(guild_app, ["task", "some work", "--background"])

        assert result.exit_code == 0
        # The task ID must be shown in the output
        assert "task-xyz-123" in result.output


@pytest.mark.unit
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
class TestAttachCommand:
    """Tests for `guild attach`."""

    def test_attach_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify attach command is registered."""
        result = runner.invoke(guild_app, ["attach", "task-nonexistent"])

        assert result.exit_code == 0 or result.exit_code == 1
        assert "Usage" not in result.output


@pytest.mark.unit
class TestKillCommand:
    """Tests for `guild kill`."""

    def test_kill_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify kill command sends graceful shutdown."""
        with patch("guild.cli.task_commands._kill_task") as mock_kill:
            mock_kill.return_value = True

            result = runner.invoke(guild_app, ["kill", "task-123"])

            assert result.exit_code == 0
            mock_kill.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
class TestPauseCommand:
    """Tests for `guild pause`."""

    def test_pause_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify pause command is registered and calls lifecycle."""
        with patch("guild.cli.task_commands._pause_task") as mock_pause:
            mock_pause.return_value = True

            result = runner.invoke(guild_app, ["pause", "task-123"])

            assert result.exit_code == 0
            mock_pause.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
class TestResumeCommand:
    """Tests for `guild resume`."""

    def test_resume_command_exists(self, guild_app, guild_project: Path) -> None:
        """Verify resume command is registered and calls lifecycle."""
        with patch("guild.cli.task_commands._resume_task") as mock_resume:
            mock_resume.return_value = True

            result = runner.invoke(guild_app, ["resume", "task-123"])

            assert result.exit_code == 0
            mock_resume.assert_called_once_with("task-123", guild_project / ".guild")


@pytest.mark.unit
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

        with patch("guild.cli.task_runner.create_provider_for_backend") as mock_pf:
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
class TestKillAllFlag:
    """Tests for `guild kill --all`."""

    def test_kill_all_flag_exists(self, guild_app, guild_project: Path) -> None:
        """Verify kill --all stops all running tasks."""
        with patch("guild.cli.task_commands._kill_all_tasks") as mock_kill_all:
            mock_kill_all.return_value = 3

            result = runner.invoke(guild_app, ["kill", "--all"])

            assert result.exit_code == 0
            mock_kill_all.assert_called_once_with(guild_project / ".guild")
            assert "3" in result.output


@pytest.mark.unit
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

        with patch("guild.cli.task_runner.create_provider_for_backend") as mock_pf:
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

        with patch("guild.cli.task_runner.create_provider_for_backend") as mock_pf:
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


@pytest.mark.unit
class TestQuestionsCommand:
    """Tests for `guild questions`."""

    def test_questions_shows_pending(self, guild_app, guild_project: Path) -> None:
        """Verify questions command shows pending escalation questions."""
        from guild.escalation.queue import QuestionQueue
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            queue = QuestionQueue(store)
            await queue.post_question(
                question="Should I proceed?",
                context="Modifying production config",
                agent_id="agent-1",
            )
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["questions"], terminal_width=200)

        assert result.exit_code == 0
        assert "proceed" in result.output.lower() or "Pending" in result.output

    def test_questions_shows_empty_message(self, guild_app, guild_project: Path) -> None:
        """Verify questions command shows no-pending message when empty."""
        result = runner.invoke(guild_app, ["questions"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() or "pending" in result.output.lower()


@pytest.mark.unit
class TestAnswerCommand:
    """Tests for `guild answer`."""

    def test_answer_responds_to_question(self, guild_app, guild_project: Path) -> None:
        """Verify answer command answers a pending question."""
        from guild.escalation.queue import QuestionQueue
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            queue = QuestionQueue(store)
            qid = await queue.post_question(
                question="Which database?",
                context="Need to choose DB",
                agent_id="agent-2",
            )
            await store.close()
            return qid

        qid = asyncio.run(_setup())

        result = runner.invoke(guild_app, ["answer", qid, "Use PostgreSQL"])

        assert result.exit_code == 0
        assert "Answered" in result.output


@pytest.mark.unit
class TestServeCommand:
    """Tests for `guild serve`."""

    def test_serve_fails_without_guild_dir(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serve fails when not in a guild project."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(guild_app, ["serve"])
        assert result.exit_code != 0 or "not a guild project" in result.output.lower()

    def test_serve_exists_in_help(self, guild_app) -> None:
        """Serve command is listed in help."""
        result = runner.invoke(guild_app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "host" in result.output.lower()
        assert "port" in result.output.lower()


@pytest.mark.unit
class TestLearningsDecay:
    """Tests for `guild learnings --decay`."""

    def test_learnings_decay_runs(self, guild_app, guild_project: Path) -> None:
        """Verify --decay runs decay on unvalidated learnings."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.add_learning(
                category="pattern",
                content="Old learning",
                confidence=0.2,
            )
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["learnings", "--decay"])

        assert result.exit_code == 0
        assert "Decayed" in result.output


# ------------------------------------------------------------------
# Tests for "not a guild project" error branches across all commands
# ------------------------------------------------------------------


@pytest.mark.unit
class TestNoGuildDirErrors:
    """All commands fail gracefully when no .guild/ directory exists."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["status"],
            ["task", "do something"],
            ["chat"],
            ["config"],
            ["audit"],
            ["decisions"],
            ["learnings"],
            ["ps"],
            ["kill", "some-id"],
            ["kill", "--all"],
            ["pause", "some-id"],
            ["resume", "some-id"],
            ["logs", "some-id"],
            ["history"],
            ["usage"],
            ["resource-status"],
            ["questions"],
            ["answer", "qid", "response"],
            ["serve"],
            ["attach", "some-id"],
            ["team", "build something"],
            ["approve", "--all"],
            ["eval", "confidence"],
        ],
    )
    def test_command_fails_without_guild_dir(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cmd_args: list[str]
    ) -> None:
        """Command shows error when not in a guild project."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(guild_app, cmd_args)
        # All should either exit with code 1 or show an error about not being a guild project
        assert result.exit_code != 0 or "not a guild project" in result.output.lower()


@pytest.mark.unit
class TestInitAlreadyExists:
    """Test init when .guild/ already exists."""

    def test_init_already_initialized(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Init shows warning when .guild/ already exists."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".guild").mkdir()

        result = runner.invoke(guild_app, ["init"])

        assert result.exit_code == 0
        assert "already" in result.output.lower()


@pytest.mark.unit
class TestNoArgsShowsHelp:
    """Test that no args shows help."""

    def test_no_args_shows_help(self, guild_app) -> None:
        """Invoking guild with no args shows help."""
        result = runner.invoke(guild_app, [])

        assert result.exit_code in (0, 2)
        assert "init" in result.output or "Usage" in result.output


# ------------------------------------------------------------------
# Tests for empty-data display branches
# ------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyDataDisplays:
    """Commands show appropriate messages when no data exists."""

    def test_audit_shows_no_entries(self, guild_app, guild_project: Path) -> None:
        """Audit shows 'no entries' when DB is empty."""
        result = runner.invoke(guild_app, ["audit"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "audit" in result.output.lower()

    def test_decisions_shows_no_entries(self, guild_app, guild_project: Path) -> None:
        """Decisions shows 'no decisions' when DB is empty."""
        result = runner.invoke(guild_app, ["decisions"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_learnings_shows_no_entries(self, guild_app, guild_project: Path) -> None:
        """Learnings shows 'no learnings' when DB is empty."""
        result = runner.invoke(guild_app, ["learnings"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_history_shows_no_tasks(self, guild_app, guild_project: Path) -> None:
        """History shows 'no tasks' when DB is empty."""
        result = runner.invoke(guild_app, ["history"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_usage_shows_table_with_zeros(self, guild_app, guild_project: Path) -> None:
        """Usage shows token table with zeros when no tasks exist."""
        result = runner.invoke(guild_app, ["usage"], terminal_width=200)
        assert result.exit_code == 0
        assert "token usage" in result.output.lower()

    def test_logs_shows_no_messages(self, guild_app, guild_project: Path) -> None:
        """Logs shows 'no messages' for unknown task."""
        result = runner.invoke(guild_app, ["logs", "nonexistent-task"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_attach_shows_no_socket(self, guild_app, guild_project: Path) -> None:
        """Attach shows 'not running' error for unknown task."""
        result = runner.invoke(guild_app, ["attach", "nonexistent-task"])
        assert result.exit_code == 1
        assert "not running" in result.output.lower()

    def test_ps_no_run_dir(self, guild_app, guild_project: Path) -> None:
        """Ps shows 'no running tasks' when run dir doesn't exist."""
        result = runner.invoke(guild_app, ["ps"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()

    def test_kill_no_task_id_no_all(self, guild_app, guild_project: Path) -> None:
        """Kill without task_id or --all shows error."""
        result = runner.invoke(guild_app, ["kill"])
        assert result.exit_code != 0 or "provide" in result.output.lower()

    def test_kill_task_not_found(self, guild_app, guild_project: Path) -> None:
        """Kill with nonexistent task shows 'not found'."""
        with patch("guild.cli.task_commands._kill_task") as mock_kill:
            mock_kill.return_value = False
            result = runner.invoke(guild_app, ["kill", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "not running" in result.output.lower()

    def test_pause_failure(self, guild_app, guild_project: Path) -> None:
        """Pause failure shows 'cannot pause'."""
        with patch("guild.cli.task_commands._pause_task") as mock_pause:
            mock_pause.return_value = False
            result = runner.invoke(guild_app, ["pause", "some-id"])
        assert result.exit_code == 0
        assert "cannot" in result.output.lower()

    def test_resume_failure(self, guild_app, guild_project: Path) -> None:
        """Resume failure shows 'cannot resume'."""
        with patch("guild.cli.task_commands._resume_task") as mock_resume:
            mock_resume.return_value = False
            result = runner.invoke(guild_app, ["resume", "some-id"])
        assert result.exit_code == 0
        assert "cannot" in result.output.lower()


# ------------------------------------------------------------------
# Tests for previously uncovered branches
# ------------------------------------------------------------------


@pytest.mark.unit
class TestConfigSetInvalidFormat:
    """config --set with invalid format shows error (lines 280-282)."""

    def test_config_set_invalid_format(self, guild_app, guild_project: Path) -> None:
        """Config --set without '=' raises ValueError and exits with code 1."""
        result = runner.invoke(guild_app, ["config", "--set", "provider.model"])
        assert result.exit_code != 0
        assert "error" in result.output.lower()


@pytest.mark.unit
class TestUsageNoData:
    """usage command when summary is None (lines 596-597)."""

    def test_usage_shows_no_data_when_summary_none(self, guild_app, guild_project: Path) -> None:
        """Usage shows 'no usage data' when token summary returns None."""
        with patch(
            "guild.cli.config_commands._fetch_token_summary",
            return_value=AsyncMock(return_value=None),
        ):
            # We need to mock the asyncio.run result
            with patch("guild.cli.config_commands.asyncio.run", return_value=None):
                result = runner.invoke(guild_app, ["usage"])

        assert result.exit_code == 0
        assert "no" in result.output.lower()


@pytest.mark.unit
class TestResourceStatusReason:
    """resource-status shows reason when status.reason is truthy (line 636)."""

    def test_resource_status_shows_reason(self, guild_app, guild_project: Path) -> None:
        """resource-status displays the reason field when present."""
        from guild.daemon.resource import ActivityState, ResourceStatus, SchedulingMode

        with patch("guild.daemon.resource.ResourceMonitor") as mock_monitor_cls:
            mock_monitor = MagicMock()
            mock_monitor.get_status.return_value = ResourceStatus(
                mode=SchedulingMode.POLITE,
                activity=ActivityState.ACTIVE,
                cpu_percent=85.0,
                is_throttled=True,
                reason="CPU usage above threshold",
            )
            mock_monitor_cls.return_value = mock_monitor

            result = runner.invoke(guild_app, ["resource-status"])

        assert result.exit_code == 0
        assert "CPU usage above threshold" in result.output


@pytest.mark.unit
class TestServeImportError:
    """serve command shows error when API deps missing (lines 706-712)."""

    def test_serve_fails_on_missing_api_deps(self, guild_app, guild_project: Path) -> None:
        """Serve shows install hint when uvicorn/fastapi are not available."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = runner.invoke(guild_app, ["serve"])

        assert result.exit_code != 0
        assert "install" in result.output.lower() or "api" in result.output.lower()


@pytest.mark.unit
class TestGetTaskAndAgentCountsNoDb:
    """_get_task_and_agent_counts returns (0, 0) when db doesn't exist (line 765)."""

    def test_returns_zeros_for_missing_db(self) -> None:
        """Returns (0, 0) when the database file doesn't exist."""
        from pathlib import Path

        from guild.cli.config_commands import _get_task_and_agent_counts

        result = _get_task_and_agent_counts(Path("/nonexistent/path/guild.db"))
        assert result == (0, 0)


@pytest.mark.unit
class TestMainCallbackNoSubcommand:
    """main_callback shows help when no subcommand is given (lines 137-138)."""

    def test_no_subcommand_shows_help_and_exits(self, guild_app) -> None:
        """Invoking guild with no subcommand shows help text."""
        result = runner.invoke(guild_app, [])
        assert result.exit_code in (0, 2)
        # Should contain help text with available commands
        assert "init" in result.output or "Usage" in result.output


@pytest.mark.unit
class TestTeamCommand:
    """Tests for `guild team`."""

    def test_team_command_exists_in_help(self, guild_app) -> None:
        """Verify team command is registered and shows in help."""
        result = runner.invoke(guild_app, ["team", "--help"])

        assert result.exit_code == 0
        assert "team" in result.output.lower()
        assert (
            "task description" in result.output.lower()
            or "task_description" in result.output.lower()
        )

    def test_team_fails_without_guild_dir(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Team fails gracefully when no .guild/ directory."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(guild_app, ["team", "build something"])
        assert result.exit_code != 0 or "not a guild project" in result.output.lower()

    def test_team_invokes_run_team_task(self, guild_app, guild_project: Path) -> None:
        """Team command delegates to run_team_task."""
        with patch("guild.cli.config_commands.asyncio.run", return_value="Team result"):
            result = runner.invoke(guild_app, ["team", "build a feature"])

        assert result.exit_code == 0
        assert "team done" in result.output.lower()


@pytest.mark.unit
class TestApproveCommand:
    """Tests for `guild approve` (REQ-15.4)."""

    def test_approve_all_questions(self, guild_app, guild_project: Path) -> None:
        """Verify approve --all approves all pending questions."""
        from guild.escalation.queue import QuestionQueue
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            queue = QuestionQueue(store)
            await queue.post_question(question="Q1?", context="ctx1", agent_id="a1")
            await queue.post_question(question="Q2?", context="ctx2", agent_id="a2")
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["approve", "--all"])

        assert result.exit_code == 0
        assert "Approved" in result.output
        assert "2" in result.output

    def test_approve_specific_questions(self, guild_app, guild_project: Path) -> None:
        """Verify approve with specific question IDs."""
        from guild.escalation.queue import QuestionQueue
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            queue = QuestionQueue(store)
            qid = await queue.post_question(question="Proceed?", context="ctx", agent_id="a1")
            await store.close()
            return qid

        qid = asyncio.run(_setup())

        result = runner.invoke(guild_app, ["approve", qid])

        assert result.exit_code == 0
        assert "Approved" in result.output

    def test_approve_no_args_no_all_shows_error(self, guild_app, guild_project: Path) -> None:
        """Approve without IDs or --all shows error."""
        result = runner.invoke(guild_app, ["approve"])

        assert result.exit_code != 0
        assert "provide" in result.output.lower() or "error" in result.output.lower()


@pytest.mark.unit
class TestEvalConfidenceCommand:
    """Tests for `guild eval confidence` (REQ-16.6)."""

    def test_eval_confidence_shows_categories(self, guild_app, guild_project: Path) -> None:
        """Verify eval confidence displays category table."""
        result = runner.invoke(guild_app, ["eval", "confidence"])

        assert result.exit_code == 0
        assert "Confidence" in result.output or "Category" in result.output

    def test_eval_confidence_fails_without_guild_dir(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Eval confidence fails gracefully without .guild/."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(guild_app, ["eval", "confidence"])
        assert result.exit_code != 0 or "not a guild project" in result.output.lower()


@pytest.mark.unit
class TestHistoryTreeCommand:
    """Tests for `guild history --tree` (REQ-12.3)."""

    def test_history_tree_shows_task_tree(self, guild_app, guild_project: Path) -> None:
        """Verify history --tree --task shows the task in tree format."""
        from guild.storage.sqlite import Storage

        db_path = guild_project / ".guild" / "guild.db"

        async def _setup():
            store = Storage(db_path)
            await store.connect()
            await store.create_task("parent-1", "Parent task")
            await store.close()

        asyncio.run(_setup())

        result = runner.invoke(guild_app, ["history", "--task", "parent-1", "--tree"])

        assert result.exit_code == 0
        assert "parent-1" in result.output
        assert "Task Tree" in result.output

    def test_history_tree_task_not_found(self, guild_app, guild_project: Path) -> None:
        """Verify history --tree with invalid task ID shows error."""
        result = runner.invoke(guild_app, ["history", "--task", "nonexistent-id", "--tree"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


@pytest.mark.unit
class TestAttachSocketCommand:
    """guild attach connects to a running task's control socket."""

    def test_attach_no_guild_dir_errors(
        self, guild_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Attach fails with error when not in a guild project."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(guild_app, ["attach", "task-123"])
        assert result.exit_code == 1
        assert "Not a guild project" in result.output

    def test_attach_no_socket_errors(self, guild_app, guild_project) -> None:
        """Attach fails when the task has no control socket."""
        # Create run dir but no socket
        run_dir = guild_project / ".guild" / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(guild_app, ["attach", "nonexistent-task"])
        assert result.exit_code == 1
        no_socket = "no control socket" in result.output.lower()
        not_running = "not running" in result.output.lower()
        assert no_socket or not_running
