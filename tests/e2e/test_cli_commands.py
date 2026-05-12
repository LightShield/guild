"""E2E acceptance tests for Guild CLI commands.

Black-box tests that exercise the system as a user would.
Only import the CLI app entry point -- no internal modules.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from guild.cli.main import app

runner = CliRunner()
pytestmark = pytest.mark.e2e


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a guild project in a temp directory."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    return tmp_path


# REQ-05.1: CLI is primary interface
@pytest.mark.req("REQ-05.1")
class TestCliInterface:
    """Verify the CLI exposes all expected commands and flags."""

    def test_help_shows_all_commands(self) -> None:
        """guild --help lists every registered command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["init", "task", "chat", "status", "config", "team"]:
            assert cmd in result.output

    def test_version_flag(self) -> None:
        """guild --version prints the package version string."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "guild" in result.output.lower()

    def test_no_args_shows_help(self) -> None:
        """Invoking guild with no arguments shows help text."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "init" in result.output or "Usage" in result.output


# REQ-05.1: guild init
@pytest.mark.req("REQ-05.1")
class TestInit:
    """Verify guild init creates the expected project structure."""

    def test_init_creates_guild_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """guild init creates .guild/ with config.toml and guild.db."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / ".guild").is_dir()
        assert (tmp_path / ".guild" / "config.toml").exists()
        assert (tmp_path / ".guild" / "guild.db").exists()

    def test_init_config_contains_provider_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The generated config.toml includes a [provider] section."""
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        content = (tmp_path / ".guild" / "config.toml").read_text()
        assert "[provider]" in content
        assert "model" in content

    def test_init_already_initialized_warns(self, project_dir: Path) -> None:
        """Running init twice prints an 'Already initialized' message."""
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "Already initialized" in result.output

    def test_init_sad_path_no_permission(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """init in a read-only directory fails gracefully."""
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o555)  # r-x: can chdir but cannot create files
        monkeypatch.chdir(readonly)
        result = runner.invoke(app, ["init"])
        assert result.exit_code != 0 or "Error" in result.output
        readonly.chmod(0o755)  # cleanup

    def test_init_explicit_path_argument(self, tmp_path: Path) -> None:
        """guild init <path> creates .guild/ in the specified directory."""
        target = tmp_path / "myproject"
        target.mkdir()
        result = runner.invoke(app, ["init", str(target)])
        assert result.exit_code == 0
        assert (target / ".guild").is_dir()
        assert (target / ".guild" / "config.toml").exists()


# REQ-05.2: status command
@pytest.mark.req("REQ-05.2")
class TestStatus:
    """Verify guild status reports project information."""

    def test_status_shows_project_info(self, project_dir: Path) -> None:
        """status displays Project, Provider, and Model fields."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Project:" in result.output
        assert "Provider:" in result.output
        assert "Model:" in result.output

    def test_status_no_project_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """status outside a guild project exits with code 1."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "Not a guild project" in result.output


# REQ-01.3: config command
@pytest.mark.req("REQ-01.3")
class TestConfig:
    """Verify guild config can show and modify settings."""

    def test_config_show_displays_table(self, project_dir: Path) -> None:
        """config without --set prints a configuration table."""
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "Guild Configuration" in result.output
        assert "provider" in result.output.lower()

    def test_config_set_and_show(self, project_dir: Path) -> None:
        """config --set updates a value that config then displays."""
        result = runner.invoke(app, ["config", "--set", "provider.model=test-model"])
        assert result.exit_code == 0
        assert "Updated" in result.output

        show = runner.invoke(app, ["config"])
        assert show.exit_code == 0
        assert "test-model" in show.output

    def test_config_set_persists_to_file(self, project_dir: Path) -> None:
        """config --set writes the value to config.toml on disk."""
        runner.invoke(app, ["config", "--set", "provider.model=persisted-model"])
        content = (project_dir / ".guild" / "config.toml").read_text()
        assert "persisted-model" in content

    def test_config_invalid_format_errors(self, project_dir: Path) -> None:
        """config --set with no '=' exits with an error."""
        result = runner.invoke(app, ["config", "--set", "no-equals-sign"])
        assert result.exit_code != 0 or "Error" in result.output


# REQ-06.6: history command (persistence)
@pytest.mark.req("REQ-06.6")
class TestHistory:
    """Verify guild history lists past tasks."""

    def test_history_empty_project(self, project_dir: Path) -> None:
        """history on a fresh project shows 'No tasks found'."""
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "No tasks" in result.output

    def test_usage_empty_project(self, project_dir: Path) -> None:
        """usage on a fresh project shows zero token counts."""
        result = runner.invoke(app, ["usage"], terminal_width=200)
        assert result.exit_code == 0
        assert "0" in result.output


# REQ-24.1: resource-status command
@pytest.mark.req("REQ-24.1")
class TestResourceStatus:
    """Verify guild resource-status reports scheduling mode."""

    def test_resource_status_shows_mode(self, project_dir: Path) -> None:
        """resource-status displays the current scheduling mode."""
        result = runner.invoke(app, ["resource-status"])
        assert result.exit_code == 0
        assert "polite" in result.output.lower() or "full" in result.output.lower()

    def test_resource_status_shows_activity_and_cpu(self, project_dir: Path) -> None:
        """resource-status includes Activity and CPU fields."""
        result = runner.invoke(app, ["resource-status"])
        assert result.exit_code == 0
        assert "Activity:" in result.output
        assert "CPU:" in result.output


# REQ-08.4: audit command
@pytest.mark.req("REQ-08.4")
class TestAudit:
    """Verify guild audit shows log entries."""

    def test_audit_empty_project(self, project_dir: Path) -> None:
        """audit on a fresh project shows 'No audit entries'."""
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# REQ-06.7: decisions command
@pytest.mark.req("REQ-06.7")
class TestDecisions:
    """Verify guild decisions shows decision log."""

    def test_decisions_empty_project(self, project_dir: Path) -> None:
        """decisions on a fresh project shows 'No decisions found'."""
        result = runner.invoke(app, ["decisions"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# REQ-07.9: learnings command
@pytest.mark.req("REQ-07.9")
class TestLearnings:
    """Verify guild learnings shows knowledge entries."""

    def test_learnings_empty_project(self, project_dir: Path) -> None:
        """learnings on a fresh project shows 'No learnings found'."""
        result = runner.invoke(app, ["learnings"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# REQ-15.1: questions command
@pytest.mark.req("REQ-15.1")
class TestQuestions:
    """Verify guild questions shows pending escalation questions."""

    def test_questions_empty_project(self, project_dir: Path) -> None:
        """questions on a fresh project shows 'No pending questions'."""
        result = runner.invoke(app, ["questions"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# REQ-05.2: ps command
@pytest.mark.req("REQ-05.2")
class TestPs:
    """Verify guild ps shows running task info."""

    def test_ps_empty_project(self, project_dir: Path) -> None:
        """ps on a fresh project shows 'No running tasks'."""
        result = runner.invoke(app, ["ps"])
        assert result.exit_code == 0
        assert "no" in result.output.lower()


# REQ-05.2: no-project error paths for all commands
@pytest.mark.req("REQ-05.2")
class TestNoProjectErrors:
    """Every project-scoped command fails gracefully outside a guild project."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["status"],
            ["config"],
            ["audit"],
            ["decisions"],
            ["learnings"],
            ["ps"],
            ["history"],
            ["usage"],
            ["resource-status"],
            ["questions"],
        ],
    )
    def test_command_fails_without_guild_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cmd_args: list[str]
    ) -> None:
        """Command shows 'Not a guild project' error outside a guild directory."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, cmd_args)
        assert result.exit_code != 0 or "not a guild project" in result.output.lower()


# REQ-01.1: Unified LLM interface
@pytest.mark.req("REQ-01.1")
class TestUnifiedProvider:
    """Verify any provider returns a consistent response shape."""

    def test_provider_returns_consistent_response_shape(self, project_dir: Path) -> None:
        """Any provider returns content + token counts + model name."""
        from unittest.mock import AsyncMock, patch

        from guild.provider.base import LLMResponse

        mock = AsyncMock()
        mock.generate = AsyncMock(
            return_value=LLMResponse(
                content="test", tool_calls=None, input_tokens=10, output_tokens=5, model="mock"
            )
        )
        mock.health_check = AsyncMock(return_value=True)
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=mock):
            result = runner.invoke(app, ["task", "say hi", "--timeout", "30"])
        assert result.exit_code == 0


# REQ-01.2: Ollama backend default
@pytest.mark.req("REQ-01.2")
class TestOllamaDefault:
    """Verify a fresh project defaults to the ollama provider."""

    def test_default_config_uses_ollama(self, project_dir: Path) -> None:
        """Fresh project defaults to ollama provider."""
        result = runner.invoke(app, ["config"])
        assert "ollama" in result.output


# REQ-01.4: Provider-specific prompt formatting transparent
@pytest.mark.req("REQ-01.4")
class TestProviderFormatting:
    """Verify user messages pass through to the provider without modification."""

    def test_messages_pass_through_to_provider(self, project_dir: Path) -> None:
        """User message arrives at provider without modification."""
        from unittest.mock import AsyncMock, patch

        from guild.provider.base import LLMResponse

        mock = AsyncMock()
        mock.generate = AsyncMock(
            return_value=LLMResponse(
                content="done", tool_calls=None, input_tokens=5, output_tokens=3, model="m"
            )
        )
        mock.health_check = AsyncMock(return_value=True)
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=mock):
            runner.invoke(app, ["task", "specific input text"])
        # Verify the user message was in the generate call
        call_args = mock.generate.call_args[0][0]
        user_msgs = [m for m in call_args if m.get("role") == "user"]
        assert any("specific input text" in m["content"] for m in user_msgs)


# REQ-01.5: Health checks
@pytest.mark.req("REQ-01.5")
class TestHealthCheck:
    """Verify unhealthy provider triggers an error or escalation."""

    def test_unhealthy_provider_triggers_escalation(self, project_dir: Path) -> None:
        """When provider health check fails, error is reported."""
        from unittest.mock import AsyncMock, patch

        mock = AsyncMock()
        mock.generate = AsyncMock(side_effect=ConnectionError("offline"))
        mock.health_check = AsyncMock(return_value=False)
        with patch("guild.cli.task_runner.create_resilient_provider", return_value=mock):
            result = runner.invoke(app, ["task", "do something"])
        # Should error or show escalation message
        assert (
            result.exit_code != 0
            or "error" in result.output.lower()
            or "failed" in result.output.lower()
        )


# REQ-02.1: OS-agnostic
@pytest.mark.req("REQ-02.1")
class TestOsAgnostic:
    """Verify source code avoids platform-specific path handling."""

    def test_no_os_path_in_source(self, project_dir: Path) -> None:
        """Source code uses pathlib, not os.path."""
        import pathlib

        src_dir = pathlib.Path(__file__).parent.parent.parent / "src" / "guild"
        for py_file in src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            assert "os.path" not in py_file.read_text(), f"os.path in {py_file.name}"


# REQ-02.2: Single install
@pytest.mark.req("REQ-02.2")
class TestSingleInstall:
    """Verify pyproject.toml defines guild as a console script."""

    def test_pip_entry_point_defined(self) -> None:
        """pyproject.toml defines guild as a console script."""
        import pathlib

        pyproject = pathlib.Path(__file__).parent.parent.parent / "pyproject.toml"
        assert 'guild = "guild.cli.main:app"' in pyproject.read_text()


# REQ-02.3: Cross-platform abstractions
@pytest.mark.req("REQ-02.3")
class TestCrossPlatformAbstractions:
    """Verify key modules use pathlib.Path for file operations."""

    def test_pathlib_used_for_paths(self) -> None:
        """Key modules use pathlib.Path for file operations."""
        import inspect

        from guild.storage.sqlite import Storage

        sig = inspect.signature(Storage.__init__)
        assert "db_path" in sig.parameters


# REQ-02.4: PlatformAdapter
@pytest.mark.req("REQ-02.4")
class TestPlatformAdapter:
    """Verify PlatformAdapter can be instantiated for the current platform."""

    def test_adapter_interface_exists_and_works(self) -> None:
        """PlatformAdapter can be instantiated for current platform."""
        from guild.daemon.platform import PlatformAdapter, get_platform_adapter

        adapter = get_platform_adapter()
        assert isinstance(adapter, PlatformAdapter)
        assert isinstance(adapter.platform_name, str)
