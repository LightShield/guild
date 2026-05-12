"""E2E acceptance tests for security sandbox, config, escalation, eval, and provider routing.

Covers REQ-13.x (security sandbox), REQ-14.x (config), REQ-15.x (escalation),
REQ-16.x (eval framework), and REQ-17.x (provider routing).

Uses real components throughout. Only LLM provider calls are mocked.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.config.loader import ConfigWatcher, load_config
from guild.config.models import GuildConfig
from guild.config.profiles import (
    AgentProfile,
    PermissionProfile,
    load_agent_profiles,
    load_permission_profiles,
    validate_config,
)
from guild.escalation.notify import NotificationChannel, Notifier
from guild.escalation.queue import PendingQuestion, QuestionPriority, QuestionQueue
from guild.eval.framework import (
    SELF_DEV_BENCHMARKS,
    BenchmarkTask,
    EvalFramework,
    EvalMetrics,
    EvalResult,
)
from guild.provider.base import LLMProvider, LLMResponse
from guild.provider.cli_provider import CLIToolProvider
from guild.provider.escalation import (
    MODEL_CAPABILITIES,
    EscalatingProvider,
    EscalationChain,
    MalformedOutputError,
    ModelCapability,
    select_model_for_task,
)
from guild.provider.retry import RetryConfig, RetryProvider
from guild.security.sandbox import SandboxPolicy, load_sandbox_policy
from guild.storage.sqlite import Storage

runner = CliRunner()
pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_provider(
    content: str = "Done.",
    tool_calls: list[dict[str, Any]] | None = None,
    input_tokens: int = 50,
    output_tokens: int = 30,
    model: str = "mock-model",
) -> AsyncMock:
    """Create a mock LLM provider returning a fixed response."""
    provider = AsyncMock(spec=LLMProvider)
    provider.generate = AsyncMock(
        return_value=LLMResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        ),
    )
    provider.health_check = AsyncMock(return_value=True)
    provider.model = model
    return provider


def _failing_provider(exc: Exception) -> AsyncMock:
    """Create a mock provider that raises on generate()."""
    provider = AsyncMock(spec=LLMProvider)
    provider.generate = AsyncMock(side_effect=exc)
    provider.health_check = AsyncMock(return_value=False)
    provider.model = "failing-model"
    return provider


@pytest.fixture()
def guild_dir(tmp_path: Path) -> Path:
    """Create a minimal .guild directory for tests."""
    gd = tmp_path / ".guild"
    gd.mkdir()
    return gd


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a full Guild project via CLI."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    return tmp_path


@pytest.fixture()
async def storage(tmp_path: Path) -> Storage:
    """Create and connect an in-memory-like SQLite storage."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


# ===================================================================
# REQ-13: Security Sandbox
# ===================================================================


@pytest.mark.req("REQ-13.1")
class TestSandboxPathBoundaries:
    """REQ-13.1: Sandboxed execution — file system path boundaries."""

    def test_allowed_path_permits_subpath(self, tmp_path: Path) -> None:
        """Paths within allowed_paths are accepted."""
        policy = SandboxPolicy(allowed_paths=[str(tmp_path)])
        allowed, reason = policy.check_path(str(tmp_path / "sub" / "file.txt"))
        assert allowed is True
        assert reason == ""

    def test_path_outside_allowed_is_rejected(self, tmp_path: Path) -> None:
        """Paths outside all allowed_paths are rejected."""
        policy = SandboxPolicy(allowed_paths=[str(tmp_path / "safe")])
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "outside all allowed" in reason

    def test_no_allowed_paths_means_all_allowed(self) -> None:
        """Empty allowed_paths permits everything."""
        policy = SandboxPolicy()
        allowed, _ = policy.check_path("/any/path")
        assert allowed is True

    def test_denied_takes_precedence_over_allowed(self, tmp_path: Path) -> None:
        """Denied paths override allowed paths."""
        policy = SandboxPolicy(
            allowed_paths=[str(tmp_path)],
            denied_paths=[str(tmp_path / "secrets")],
        )
        allowed, reason = policy.check_path(str(tmp_path / "secrets" / "key.pem"))
        assert allowed is False
        assert "denied" in reason.lower()

    def test_load_sandbox_policy_from_toml(self, guild_dir: Path) -> None:
        """Load policy from a security.toml file with filesystem rules."""
        security_toml = guild_dir / "security.toml"
        security_toml.write_text(
            '[filesystem]\n'
            f'allowed_paths = ["{guild_dir.parent}"]\n'
            f'denied_paths = ["{guild_dir.parent}/private"]\n'
        )
        policy = load_sandbox_policy(guild_dir)
        assert str(guild_dir.parent) in policy.allowed_paths
        assert str(guild_dir.parent / "private") in policy.denied_paths


@pytest.mark.req("REQ-13.2")
class TestSandboxNetwork:
    """REQ-13.2: Network access controls per agent."""

    def test_network_disabled_by_policy(self) -> None:
        """When network_allowed=False, policy reflects it."""
        policy = SandboxPolicy(network_allowed=False)
        assert policy.network_allowed is False

    def test_network_hosts_allowlist(self) -> None:
        """Hosts allowlist restricts which endpoints are contactable."""
        policy = SandboxPolicy(
            network_hosts_allowlist=["api.example.com", "localhost"],
        )
        assert "api.example.com" in policy.network_hosts_allowlist
        assert "evil.com" not in policy.network_hosts_allowlist

    def test_load_network_policy_from_toml(self, guild_dir: Path) -> None:
        """Load network controls from security.toml."""
        security_toml = guild_dir / "security.toml"
        security_toml.write_text(
            '[network]\n'
            'allowed = false\n'
            'hosts_allowlist = ["localhost"]\n'
        )
        policy = load_sandbox_policy(guild_dir)
        assert policy.network_allowed is False
        assert policy.network_hosts_allowlist == ["localhost"]


@pytest.mark.req("REQ-13.3")
class TestSandboxSecrets:
    """REQ-13.3: Secret management — agents use API keys without seeing values."""

    def test_mask_secrets_in_text(self) -> None:
        """Secret values are replaced with [REDACTED:name] in output text."""
        policy = SandboxPolicy(secrets={"API_KEY": "sk-12345"})
        masked = policy.mask_secrets("Authorization: Bearer sk-12345")
        assert "sk-12345" not in masked
        assert "[REDACTED:API_KEY]" in masked

    def test_inject_secret_into_command(self) -> None:
        """${SECRET_NAME} placeholders are replaced with actual values."""
        policy = SandboxPolicy(secrets={"DB_PASS": "hunter2"})
        result = policy.inject_secret("psql -p ${DB_PASS} mydb")
        assert result == "psql -p hunter2 mydb"

    def test_unknown_placeholder_left_unchanged(self) -> None:
        """Unregistered ${PLACEHOLDERS} pass through unchanged."""
        policy = SandboxPolicy(secrets={"KNOWN": "val"})
        result = policy.inject_secret("echo ${UNKNOWN}")
        assert result == "echo ${UNKNOWN}"

    def test_secrets_loaded_from_toml(self, guild_dir: Path) -> None:
        """Secrets section in security.toml is parsed into policy."""
        security_toml = guild_dir / "security.toml"
        security_toml.write_text(
            '[secrets]\n'
            'API_KEY = "test-secret-val"\n'
        )
        policy = load_sandbox_policy(guild_dir)
        assert policy.secrets["API_KEY"] == "test-secret-val"


@pytest.mark.req("REQ-13.4")
class TestSandboxFileBoundaries:
    """REQ-13.4: File system boundaries — agents only access allowed paths."""

    def test_exact_path_match_is_allowed(self, tmp_path: Path) -> None:
        """Exact match on an allowed path is permitted."""
        policy = SandboxPolicy(allowed_paths=[str(tmp_path / "workspace")])
        allowed, _ = policy.check_path(str(tmp_path / "workspace"))
        assert allowed is True

    def test_parent_traversal_blocked(self, tmp_path: Path) -> None:
        """Paths with .. that escape allowed boundaries are blocked."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = SandboxPolicy(allowed_paths=[str(workspace)])
        allowed, reason = policy.check_path(str(workspace / ".." / "other"))
        assert allowed is False
        assert "outside" in reason


@pytest.mark.req("REQ-13.5")
class TestSandboxCommandDenylist:
    """REQ-13.5: Command allowlist/denylist for shell execution."""

    def test_denied_command_rejected(self) -> None:
        """Commands in denylist are blocked."""
        policy = SandboxPolicy(denied_commands=["rm", "curl"])
        allowed, reason = policy.check_command("rm -rf /tmp/stuff")
        assert allowed is False
        assert "denylist" in reason

    def test_allowed_command_accepted(self) -> None:
        """Commands in allowlist are accepted."""
        policy = SandboxPolicy(allowed_commands=["ls", "cat", "grep"])
        allowed, _ = policy.check_command("ls -la")
        assert allowed is True

    def test_command_not_in_allowlist_rejected(self) -> None:
        """When allowlist is set, unlisted commands are rejected."""
        policy = SandboxPolicy(allowed_commands=["ls", "cat"])
        allowed, reason = policy.check_command("wget http://evil.com")
        assert allowed is False
        assert "not in allowlist" in reason

    def test_deny_takes_precedence_over_allow(self) -> None:
        """Denylist overrides allowlist."""
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget"],
            denied_commands=["curl"],
        )
        allowed, reason = policy.check_command("curl http://example.com")
        assert allowed is False

    def test_no_restrictions_allows_all(self) -> None:
        """Empty allow and deny lists permit everything."""
        policy = SandboxPolicy()
        allowed, _ = policy.check_command("anything")
        assert allowed is True


# ===================================================================
# REQ-14: Configuration
# ===================================================================


@pytest.mark.req("REQ-14.1")
class TestConfigAgentDefinitions:
    """REQ-14.1: TOML-based agent definitions in .guild/agents.toml."""

    def test_load_agent_profiles_from_toml(self, guild_dir: Path) -> None:
        """Agent profiles are loaded from agents.toml."""
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text(
            '[planner]\n'
            'model = "gemma4-4b-dense-med"\n'
            'system_prompt = "You plan tasks."\n'
            'tools = ["file_read", "search"]\n'
            'permission = "scoped"\n'
            'max_turns = 20\n'
            'token_budget = 5000\n'
        )
        profiles = load_agent_profiles(guild_dir)
        assert "planner" in profiles
        planner = profiles["planner"]
        assert planner.model == "gemma4-4b-dense-med"
        assert planner.tools == ["file_read", "search"]
        assert planner.permission == "scoped"
        assert planner.max_turns == 20
        assert planner.token_budget == 5000

    def test_multiple_agent_profiles(self, guild_dir: Path) -> None:
        """Multiple agent profiles can coexist in one file."""
        agents_toml = guild_dir / "agents.toml"
        agents_toml.write_text(
            '[planner]\nmodel = "model-a"\nsystem_prompt = "Plan."\n\n'
            '[coder]\nmodel = "model-b"\nsystem_prompt = "Code."\n'
        )
        profiles = load_agent_profiles(guild_dir)
        assert len(profiles) == 2
        assert "planner" in profiles
        assert "coder" in profiles


@pytest.mark.req("REQ-14.2")
class TestConfigTeamDefinitions:
    """REQ-14.2: TOML-based team definitions loaded from block files."""

    def test_team_block_loading(self, project_dir: Path) -> None:
        """Team block TOML files are loadable from .guild/blocks."""
        blocks_dir = project_dir / ".guild" / "blocks"
        blocks_dir.mkdir(exist_ok=True)
        (blocks_dir / "team_qa.toml").write_text(
            '[team]\nname = "qa"\nentry_block = "test"\n'
            '\n[team.blocks]\ntest = "tester"\n'
        )
        # Verify the file can be loaded as TOML
        import tomllib

        with open(blocks_dir / "team_qa.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["team"]["name"] == "qa"
        assert data["team"]["entry_block"] == "test"


@pytest.mark.req("REQ-14.3")
class TestConfigPermissionProfiles:
    """REQ-14.3: Named permission profiles from .guild/permissions.toml."""

    def test_load_permission_profiles(self, guild_dir: Path) -> None:
        """Permission profiles are loaded from permissions.toml."""
        perms_toml = guild_dir / "permissions.toml"
        perms_toml.write_text(
            '[restricted]\n'
            'tier = "scoped"\n'
            'allowed_paths = ["/safe"]\n'
            'allowed_tools = ["file_read"]\n'
        )
        profiles = load_permission_profiles(guild_dir)
        assert "restricted" in profiles
        assert profiles["restricted"].tier == "scoped"
        assert profiles["restricted"].allowed_paths == ["/safe"]
        assert profiles["restricted"].allowed_tools == ["file_read"]

    def test_empty_permission_profiles(self, guild_dir: Path) -> None:
        """Missing permissions.toml returns empty dict, not error."""
        profiles = load_permission_profiles(guild_dir)
        assert profiles == {}


@pytest.mark.req("REQ-14.4")
class TestConfigOverrides:
    """REQ-14.4: Project config overrides global config."""

    def test_project_overrides_global(self, tmp_path: Path) -> None:
        """Project config.toml values override global defaults."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_toml = guild_dir / "config.toml"
        config_toml.write_text(
            '[provider]\nmodel = "custom-model"\nbase_url = "http://custom:11434"\n'
        )
        config = load_config(guild_dir=guild_dir)
        assert config.model == "custom-model"
        assert config.base_url == "http://custom:11434"

    def test_cli_args_override_config_file(self, tmp_path: Path) -> None:
        """CLI arguments take highest priority over file config."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config_toml = guild_dir / "config.toml"
        config_toml.write_text('[provider]\nmodel = "from-file"\n')
        config = load_config(guild_dir=guild_dir, args=["--model", "from-cli"])
        assert config.model == "from-cli"


@pytest.mark.req("REQ-14.5")
class TestConfigValidation:
    """REQ-14.5: Config validation on startup."""

    def test_valid_config_no_errors(self, project_dir: Path) -> None:
        """A properly initialized project passes validation."""
        guild_dir = project_dir / ".guild"
        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)
        assert errors == []

    def test_missing_model_is_error(self, tmp_path: Path) -> None:
        """Empty model name is flagged as validation error."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nmodel = ""\nbase_url = "http://localhost:11434"\n'
        )
        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)
        assert any("model" in e.lower() for e in errors)

    def test_invalid_agent_permission_is_error(self, tmp_path: Path) -> None:
        """Agent profile referencing an invalid permission tier is flagged."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nmodel = "m"\nbase_url = "http://x"\n'
        )
        (guild_dir / "agents.toml").write_text(
            '[bad_agent]\npermission = "nonexistent_tier"\n'
        )
        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)
        assert any("bad_agent" in e for e in errors)


@pytest.mark.req("REQ-14.6")
class TestConfigHotReload:
    """REQ-14.6: Hot-reload config on file change."""

    def test_config_watcher_detects_change(self, tmp_path: Path) -> None:
        """ConfigWatcher fires callback when config file mtime changes."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[provider]\nmodel = "old"\n')

        callback_called = []
        watcher = ConfigWatcher(config_file, callback=lambda: callback_called.append(True))

        # No change yet
        assert watcher.check_for_changes() is False
        assert len(callback_called) == 0

        # Modify the file — ensure mtime changes
        time.sleep(0.05)
        config_file.write_text('[provider]\nmodel = "new"\n')

        assert watcher.check_for_changes() is True
        assert len(callback_called) == 1

    def test_config_watcher_no_spurious_reload(self, tmp_path: Path) -> None:
        """ConfigWatcher does not fire when mtime is unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[provider]\nmodel = "stable"\n')

        callback_called = []
        watcher = ConfigWatcher(config_file, callback=lambda: callback_called.append(True))

        # Multiple checks without file change
        for _ in range(5):
            assert watcher.check_for_changes() is False
        assert len(callback_called) == 0

    def test_config_watcher_missing_file(self, tmp_path: Path) -> None:
        """ConfigWatcher handles missing config file gracefully."""
        missing = tmp_path / "nonexistent.toml"
        watcher = ConfigWatcher(missing, callback=lambda: None)
        assert watcher.check_for_changes() is False


# ===================================================================
# REQ-15: Escalation
# ===================================================================


@pytest.mark.req("REQ-15.2")
class TestEscalationPresenceNotify:
    """REQ-15.2: Presence-aware notification for escalation questions."""

    async def test_notify_via_terminal_bell(self) -> None:
        """Terminal bell notification channel sends bell character."""
        notifier = Notifier(channels=[NotificationChannel.TERMINAL_BELL])
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify("Test notification")
        mock_stdout.write.assert_called_with("\a")

    async def test_notify_via_none_channel(self) -> None:
        """None channel silently discards notifications."""
        notifier = Notifier(channels=[NotificationChannel.NONE])
        # Should not raise
        await notifier.notify("Silenced")

    async def test_notify_high_priority(self) -> None:
        """High-priority notifications are dispatched through channels."""
        notifier = Notifier(channels=[NotificationChannel.TERMINAL_BELL])
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify(
                "Urgent question", priority=QuestionPriority.BLOCKING,
            )
        mock_stdout.write.assert_called()


@pytest.mark.req("REQ-15.3")
class TestEscalationContext:
    """REQ-15.3: Questions carry context for the human reviewer."""

    async def test_question_includes_context(self, storage: Storage) -> None:
        """Posted questions include context string for human review."""
        queue = QuestionQueue(storage)
        q_id = await queue.post_question(
            question="Should I refactor?",
            context="The function is 200 lines long and has 8 parameters.",
            task_id="task-1",
            agent_id="agent-1",
        )
        pending = await queue.get_pending()
        matched = [q for q in pending if q.id == q_id]
        assert len(matched) == 1
        assert "200 lines" in matched[0].context

    async def test_question_preserves_agent_and_task_ids(self, storage: Storage) -> None:
        """Questions carry task_id and agent_id for traceability."""
        queue = QuestionQueue(storage)
        q_id = await queue.post_question(
            question="Proceed?",
            context="Context here.",
            task_id="t-42",
            agent_id="a-7",
        )
        pending = await queue.get_pending()
        matched = [q for q in pending if q.id == q_id]
        assert matched[0].task_id == "t-42"
        assert matched[0].agent_id == "a-7"


@pytest.mark.req("REQ-15.4")
class TestEscalationBatchApproval:
    """REQ-15.4: Batch approval of multiple pending questions."""

    async def test_batch_answer_multiple_questions(self, storage: Storage) -> None:
        """Multiple questions can be answered in a single batch call."""
        queue = QuestionQueue(storage)
        q1 = await queue.post_question(
            question="Q1?", context="ctx1",
        )
        q2 = await queue.post_question(
            question="Q2?", context="ctx2",
        )
        q3 = await queue.post_question(
            question="Q3?", context="ctx3",
        )

        count = await queue.batch_answer({q1: "Yes", q2: "No", q3: "Maybe"})
        assert count == 3

        # All should now be answered
        a1 = await queue.get_answer(q1)
        a2 = await queue.get_answer(q2)
        a3 = await queue.get_answer(q3)
        assert a1 == "Yes"
        assert a2 == "No"
        assert a3 == "Maybe"

    async def test_batch_answer_returns_correct_count(self, storage: Storage) -> None:
        """Batch answer returns the exact count of answered questions."""
        queue = QuestionQueue(storage)
        q1 = await queue.post_question(question="A?", context="c")
        q2 = await queue.post_question(question="B?", context="c")
        count = await queue.batch_answer({q1: "Ans1", q2: "Ans2"})
        assert count == 2


@pytest.mark.req("REQ-15.5")
class TestEscalationChannels:
    """REQ-15.5: Configurable notification channels."""

    async def test_multiple_channels(self) -> None:
        """Notifier dispatches to all configured channels."""
        notifier = Notifier(
            channels=[NotificationChannel.TERMINAL_BELL, NotificationChannel.NONE],
        )
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify("Multi-channel test")
        # Bell should have fired (NONE is silent)
        mock_stdout.write.assert_called_with("\a")

    async def test_webhook_channel_posts_json(self) -> None:
        """Webhook channel sends an HTTP POST with JSON payload."""
        notifier = Notifier(
            channels=[NotificationChannel.WEBHOOK],
            webhook_url="http://hooks.example.com/notify",
        )
        with patch("guild.escalation.notify._post_json", new_callable=AsyncMock) as mock_post:
            await notifier.notify("Webhook test")
        mock_post.assert_awaited_once_with(
            "http://hooks.example.com/notify", {"text": "Webhook test"},
        )

    async def test_webhook_without_url_logs_warning(self) -> None:
        """Webhook channel without URL logs a warning instead of crashing."""
        notifier = Notifier(
            channels=[NotificationChannel.WEBHOOK],
            webhook_url=None,
        )
        # Should not raise
        await notifier.notify("No URL configured")

    async def test_desktop_channel_calls_platform_adapter(self) -> None:
        """Desktop channel invokes the platform adapter."""
        notifier = Notifier(channels=[NotificationChannel.DESKTOP])
        mock_adapter = MagicMock()
        with patch(
            "guild.escalation.notify.get_platform_adapter",
            return_value=mock_adapter,
        ):
            await notifier.notify("Desktop alert")
        mock_adapter.send_desktop_notification.assert_called_once()


# ===================================================================
# REQ-16: Eval Framework
# ===================================================================


@pytest.mark.req("REQ-16.1")
class TestEvalABTest:
    """REQ-16.1: A/B testing of different configs/models."""

    async def test_ab_test_runs_both_providers(self, storage: Storage) -> None:
        """A/B test runs the same task on two providers and returns both results."""
        framework = EvalFramework(storage)
        task = BenchmarkTask(
            name="ab_test_task",
            description="Write hello world.",
            verification=[],
        )
        provider_a = _mock_provider(model="model-a", input_tokens=100, output_tokens=50)
        provider_b = _mock_provider(model="model-b", input_tokens=200, output_tokens=100)

        result_a, result_b = await framework.run_ab_test(
            task, provider_a, provider_b, "config-a", "config-b",
        )
        assert result_a.model == "model-a"
        assert result_b.model == "model-b"
        assert result_a.task_name == result_b.task_name == "ab_test_task"

    async def test_compare_results_determines_winner(self, storage: Storage) -> None:
        """Compare results picks a winner based on metrics."""
        framework = EvalFramework(storage)
        result_a = EvalResult(
            task_name="t", model="a", config_hash="ha",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=1.0,
                input_tokens=100, output_tokens=50, tool_calls=2, turns=3,
            ),
            timestamp="2026-01-01",
        )
        result_b = EvalResult(
            task_name="t", model="b", config_hash="hb",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=5.0,
                input_tokens=500, output_tokens=250, tool_calls=10, turns=8,
            ),
            timestamp="2026-01-01",
        )
        comparison = framework.compare_results(result_a, result_b)
        assert comparison["winner"] == "a"


@pytest.mark.req("REQ-16.2")
class TestEvalBenchmarkSuite:
    """REQ-16.2: Standard benchmark suite execution."""

    async def test_run_suite_returns_results_for_all_tasks(self, storage: Storage) -> None:
        """run_suite returns one result per task."""
        framework = EvalFramework(storage)
        tasks = [
            BenchmarkTask(name="t1", description="Do thing 1.", verification=[]),
            BenchmarkTask(name="t2", description="Do thing 2.", verification=[]),
            BenchmarkTask(name="t3", description="Do thing 3.", verification=[]),
        ]
        provider = _mock_provider()
        results = await framework.run_suite(tasks, provider, "bench-run")
        assert len(results) == 3
        assert [r.task_name for r in results] == ["t1", "t2", "t3"]

    async def test_suite_collects_metrics(self, storage: Storage) -> None:
        """Each suite result contains valid metrics."""
        framework = EvalFramework(storage)
        task = BenchmarkTask(name="metric_task", description="Do it.", verification=[])
        provider = _mock_provider(input_tokens=100, output_tokens=80)
        results = await framework.run_suite([task], provider, "m")
        r = results[0]
        assert r.metrics.task_completed is True
        assert r.metrics.input_tokens == 100
        assert r.metrics.output_tokens == 80
        assert r.metrics.turns >= 1


@pytest.mark.req("REQ-16.3")
class TestEvalRegressionDetection:
    """REQ-16.3: Regression detection via metric comparison."""

    async def test_task_failure_is_regression(self, storage: Storage) -> None:
        """If baseline completed but current failed, it is a regression."""
        framework = EvalFramework(storage)
        baseline = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=1.0,
                input_tokens=100, output_tokens=50, tool_calls=2, turns=3,
            ),
            timestamp="2026-01-01",
        )
        current = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=False, duration_seconds=0.5,
                input_tokens=50, output_tokens=20, tool_calls=1, turns=1,
                error="Timed out",
            ),
            timestamp="2026-01-02",
        )
        regressed, reason = framework.detect_regression(current, baseline)
        assert regressed is True
        assert "no longer completes" in reason

    async def test_duration_regression(self, storage: Storage) -> None:
        """2x duration increase is flagged as regression."""
        framework = EvalFramework(storage)
        baseline = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=1.0,
                input_tokens=100, output_tokens=50, tool_calls=2, turns=3,
            ),
            timestamp="2026-01-01",
        )
        current = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=3.0,
                input_tokens=100, output_tokens=50, tool_calls=2, turns=3,
            ),
            timestamp="2026-01-02",
        )
        regressed, reason = framework.detect_regression(current, baseline)
        assert regressed is True
        assert "duration" in reason

    async def test_no_regression_within_threshold(self, storage: Storage) -> None:
        """Slightly slower run is not a regression."""
        framework = EvalFramework(storage)
        baseline = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=1.0,
                input_tokens=100, output_tokens=50, tool_calls=2, turns=3,
            ),
            timestamp="2026-01-01",
        )
        current = EvalResult(
            task_name="t", model="m", config_hash="h",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=1.5,
                input_tokens=120, output_tokens=60, tool_calls=3, turns=4,
            ),
            timestamp="2026-01-02",
        )
        regressed, _ = framework.detect_regression(current, baseline)
        assert regressed is False


@pytest.mark.req("REQ-16.4")
class TestEvalMetricsCollection:
    """REQ-16.4: Eval metrics — tokens, duration, tool calls, turns."""

    async def test_eval_run_collects_all_metric_fields(self, storage: Storage) -> None:
        """A single eval run populates all EvalMetrics fields."""
        framework = EvalFramework(storage)
        task = BenchmarkTask(name="full_metrics", description="Go.", verification=[])
        provider = _mock_provider(input_tokens=200, output_tokens=100)
        result = await framework.run_eval(task, provider, "cfg")
        m = result.metrics
        assert isinstance(m.task_completed, bool)
        assert m.duration_seconds > 0
        assert m.input_tokens == 200
        assert m.output_tokens == 100
        assert m.turns >= 1
        assert m.error is None

    async def test_eval_captures_errors(self, storage: Storage) -> None:
        """Provider failure is captured in metrics error field."""
        framework = EvalFramework(storage)
        task = BenchmarkTask(name="error_task", description="Fail.", verification=[])
        failing = _failing_provider(ConnectionError("network down"))
        result = await framework.run_eval(task, failing, "cfg")
        assert result.metrics.task_completed is False
        assert result.metrics.error is not None
        assert "network down" in result.metrics.error


@pytest.mark.req("REQ-16.5")
class TestEvalResultsPersistence:
    """REQ-16.5: Persistent storage and retrieval of eval results."""

    async def test_store_and_retrieve_result(self, storage: Storage) -> None:
        """Eval results persist to SQLite and can be retrieved."""
        framework = EvalFramework(storage)
        result = EvalResult(
            task_name="persist_test", model="test-model", config_hash="h1",
            metrics=EvalMetrics(
                task_completed=True, duration_seconds=2.5,
                input_tokens=150, output_tokens=75, tool_calls=3, turns=4,
            ),
            timestamp="2026-01-01T00:00:00",
        )
        await framework.store_result(result)
        results = await framework.get_results(task_name="persist_test")
        assert len(results) >= 1
        stored = results[0]
        assert stored.task_name == "persist_test"
        assert stored.model == "test-model"
        assert stored.metrics.input_tokens == 150

    async def test_retrieve_with_limit(self, storage: Storage) -> None:
        """Result retrieval respects the limit parameter."""
        framework = EvalFramework(storage)
        for i in range(5):
            result = EvalResult(
                task_name="limit_test", model="m", config_hash=f"h{i}",
                metrics=EvalMetrics(
                    task_completed=True, duration_seconds=1.0,
                    input_tokens=10, output_tokens=5, tool_calls=1, turns=1,
                ),
                timestamp=f"2026-01-0{i + 1}",
            )
            await framework.store_result(result)
        results = await framework.get_results(task_name="limit_test", limit=3)
        assert len(results) == 3


@pytest.mark.req("REQ-16.6")
class TestEvalProgressiveConfidence:
    """REQ-16.6: Progressive confidence — benchmark difficulty ramps up."""

    def test_self_dev_benchmarks_ordered_by_complexity(self) -> None:
        """Built-in benchmarks progress from simple to complex."""
        assert len(SELF_DEV_BENCHMARKS) >= 2
        # First task is simpler (fewer verification steps)
        first = SELF_DEV_BENCHMARKS[0]
        last = SELF_DEV_BENCHMARKS[-1]
        assert len(last.verification) >= len(first.verification)

    def test_self_dev_benchmarks_have_required_fields(self) -> None:
        """Each benchmark has name, description, and verification."""
        for task in SELF_DEV_BENCHMARKS:
            assert task.name
            assert task.description
            assert isinstance(task.verification, list)


@pytest.mark.req("REQ-16.7")
class TestEvalSelfDevBenchmarks:
    """REQ-16.7: Self-development benchmark suite for Guild itself."""

    def test_self_dev_benchmarks_cover_categories(self) -> None:
        """Self-dev benchmarks include both general and coding categories."""
        categories = {t.category for t in SELF_DEV_BENCHMARKS}
        assert "general" in categories
        assert "coding" in categories

    async def test_self_dev_benchmarks_runnable(self, storage: Storage) -> None:
        """Self-dev benchmarks can be executed against a mock provider."""
        framework = EvalFramework(storage)
        provider = _mock_provider()
        results = await framework.run_suite(SELF_DEV_BENCHMARKS, provider, "self-dev")
        assert len(results) == len(SELF_DEV_BENCHMARKS)
        for r in results:
            assert r.metrics.task_completed is True


# ===================================================================
# REQ-17: Provider Routing
# ===================================================================


@pytest.mark.req("REQ-17.1")
class TestProviderPerAgentModel:
    """REQ-17.1: Per-agent model selection via agent profiles."""

    def test_agent_profile_specifies_model(self, guild_dir: Path) -> None:
        """Agent profiles carry per-agent model selection."""
        (guild_dir / "agents.toml").write_text(
            '[fast_agent]\nmodel = "gemma4-2b-edge-fast"\n\n'
            '[smart_agent]\nmodel = "gemma4-26b-moe-agent"\n'
        )
        profiles = load_agent_profiles(guild_dir)
        assert profiles["fast_agent"].model == "gemma4-2b-edge-fast"
        assert profiles["smart_agent"].model == "gemma4-26b-moe-agent"

    def test_agent_profile_without_model_uses_none(self, guild_dir: Path) -> None:
        """Agent profiles without explicit model default to None (use global)."""
        (guild_dir / "agents.toml").write_text(
            '[default_agent]\nsystem_prompt = "Hi."\n'
        )
        profiles = load_agent_profiles(guild_dir)
        assert profiles["default_agent"].model is None


@pytest.mark.req("REQ-17.2")
class TestProviderFallbackChains:
    """REQ-17.2: Escalation chain — fallback through ordered provider list."""

    async def test_chain_escalates_on_failure(self) -> None:
        """EscalationChain moves to next provider when current fails."""
        primary = _failing_provider(ConnectionError("down"))
        secondary = _mock_provider(model="secondary")

        chain = EscalationChain([primary, secondary])
        ep = EscalatingProvider(chain)

        result = await ep.generate([{"role": "user", "content": "Hello"}])
        assert result.model == "secondary"
        assert chain.current_index == 1

    async def test_chain_raises_when_exhausted(self) -> None:
        """When all providers fail, the last exception propagates."""
        p1 = _failing_provider(ConnectionError("down1"))
        p2 = _failing_provider(ConnectionError("down2"))

        chain = EscalationChain([p1, p2])
        ep = EscalatingProvider(chain)

        with pytest.raises(ConnectionError):
            await ep.generate([{"role": "user", "content": "Hello"}])

    def test_chain_requires_at_least_one_provider(self) -> None:
        """Empty provider list raises ValueError."""
        with pytest.raises(ValueError, match="at least one"):
            EscalationChain([])


@pytest.mark.req("REQ-17.3")
class TestProviderCheapModels:
    """REQ-17.3: Select cheapest capable model for a task type."""

    def test_select_cheapest_for_simple_qa(self) -> None:
        """Simple QA selects the cheapest model with simple_qa tag."""
        models = list(MODEL_CAPABILITIES.keys())
        selected = select_model_for_task("simple_qa", models)
        cap = MODEL_CAPABILITIES[selected]
        assert "simple_qa" in cap.tags
        assert cap.cost_tier == "free"

    def test_select_model_for_code_generation(self) -> None:
        """Code generation selects a capable model."""
        models = list(MODEL_CAPABILITIES.keys())
        selected = select_model_for_task("code_generation", models)
        cap = MODEL_CAPABILITIES[selected]
        assert "code_generation" in cap.tags

    def test_no_capable_model_raises(self) -> None:
        """ValueError when no model supports the requested capability."""
        with pytest.raises(ValueError, match="No available model"):
            select_model_for_task("nonexistent_capability", list(MODEL_CAPABILITIES.keys()))


@pytest.mark.req("REQ-17.4")
class TestProviderCapabilityTags:
    """REQ-17.4: Models have capability tags for routing decisions."""

    def test_model_capabilities_have_tags(self) -> None:
        """All registered models have at least one capability tag."""
        for key, cap in MODEL_CAPABILITIES.items():
            assert len(cap.tags) > 0, f"Model {key} has no tags"

    def test_model_capabilities_have_cost_tier(self) -> None:
        """All registered models have a valid cost tier."""
        valid_tiers = {"free", "cheap", "expensive"}
        for key, cap in MODEL_CAPABILITIES.items():
            assert cap.cost_tier in valid_tiers, f"Model {key} has invalid cost tier"

    def test_capability_tag_filtering(self) -> None:
        """Models can be filtered by capability tag."""
        reasoning_models = [
            k for k, v in MODEL_CAPABILITIES.items() if "reasoning" in v.tags
        ]
        assert len(reasoning_models) >= 1


@pytest.mark.req("REQ-17.5")
class TestProviderStuckEscalation:
    """REQ-17.5: Stuck detection triggers model escalation."""

    async def test_notify_stuck_escalates(self) -> None:
        """notify_stuck() moves the chain to the next provider."""
        primary = _mock_provider(model="small")
        secondary = _mock_provider(model="large")
        chain = EscalationChain([primary, secondary])
        ep = EscalatingProvider(chain)

        assert chain.current_index == 0
        escalated = ep.notify_stuck()
        assert escalated is True
        assert chain.current_index == 1

    async def test_notify_stuck_returns_false_when_exhausted(self) -> None:
        """notify_stuck() returns False when chain has no more providers."""
        single = _mock_provider(model="only")
        chain = EscalationChain([single])
        ep = EscalatingProvider(chain)

        escalated = ep.notify_stuck()
        assert escalated is False


@pytest.mark.req("REQ-17.6")
class TestProviderCLITools:
    """REQ-17.6: CLI tool providers as last-resort escalation."""

    def test_cli_provider_builds_command(self) -> None:
        """CLIToolProvider builds correct command from prompt."""
        provider = CLIToolProvider(command="gemini", model="gemini-pro")
        cmd = provider._build_command("Hello world")
        assert cmd[0] == "gemini"
        assert "--model" in cmd
        assert "gemini-pro" in cmd
        assert "-p" in cmd
        assert "Hello world" in cmd

    def test_cli_provider_extracts_prompt(self) -> None:
        """CLIToolProvider extracts last user message as prompt."""
        provider = CLIToolProvider(command="claude")
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "First question."},
            {"role": "assistant", "content": "Answer."},
            {"role": "user", "content": "Second question."},
        ]
        prompt = provider._extract_prompt(messages)
        assert prompt == "Second question."

    async def test_cli_provider_health_check(self) -> None:
        """Health check returns False for nonexistent CLI tools."""
        provider = CLIToolProvider(command="nonexistent_cli_tool_xyz")
        healthy = await provider.health_check()
        assert healthy is False

    def test_cli_provider_command_without_model(self) -> None:
        """CLI provider without explicit model uses command as model name."""
        provider = CLIToolProvider(command="claude")
        assert provider.model == "claude"
        cmd = provider._build_command("test")
        # Should not include --model when model equals command
        assert "--model" not in cmd


@pytest.mark.req("REQ-17.7")
class TestProviderConfigurableChains:
    """REQ-17.7: Configurable escalation chains via config."""

    def test_escalation_chain_config_field_exists(self) -> None:
        """GuildConfig has escalation_chain field for configurable chains."""
        config = GuildConfig.load(args=[], file=None)
        assert hasattr(config, "escalation_chain")
        assert hasattr(config, "escalation_cli_providers")

    def test_chain_length_and_navigation(self) -> None:
        """Chain tracks length and current position correctly."""
        providers = [_mock_provider(model=f"m{i}") for i in range(3)]
        chain = EscalationChain(providers)
        assert len(chain) == 3
        assert chain.current_index == 0
        assert not chain.is_exhausted

        chain.escalate()
        assert chain.current_index == 1

        chain.escalate()
        assert chain.current_index == 2
        assert chain.is_exhausted

        # Reset
        chain.reset()
        assert chain.current_index == 0

    def test_config_escalation_chain_from_toml(self, tmp_path: Path) -> None:
        """Escalation chain value loads from TOML config."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nmodel = "m"\nbase_url = "http://x"\n\n'
            '[escalation]\n'
            'escalation_chain = "model-a,model-b,model-c"\n'
            'escalation_cli_providers = "gemini,claude"\n'
        )
        config = load_config(guild_dir=guild_dir)
        assert "model-a" in config.escalation_chain
        assert "model-b" in config.escalation_chain
        assert "gemini" in config.escalation_cli_providers


@pytest.mark.req("REQ-17.8")
class TestProviderMalformedRecovery:
    """REQ-17.8: Recovery from malformed model output."""

    async def test_retry_with_correction_appends_hint(self) -> None:
        """retry_with_correction adds a correction hint message."""
        primary = _mock_provider(content="Fixed output")
        chain = EscalationChain([primary])
        ep = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "Do something"}]
        result = await ep.retry_with_correction(messages)
        assert result.content == "Fixed output"

        # Verify the correction hint was appended
        call_args = primary.generate.call_args
        sent_messages = call_args[0][0]
        assert len(sent_messages) == 2
        assert "malformed" in sent_messages[-1]["content"].lower()

    async def test_escalate_and_retry_on_malformed(self) -> None:
        """Escalation happens when correction on current provider fails."""
        primary = _mock_provider(content="Still bad")
        secondary = _mock_provider(content="Good output")
        chain = EscalationChain([primary, secondary])
        ep = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "Format this"}]
        result = await ep.escalate_and_retry(messages)
        assert result.content == "Good output"
        assert chain.current_index == 1

    async def test_malformed_error_when_chain_exhausted(self) -> None:
        """MalformedOutputError raised when no providers remain."""
        single = _mock_provider()
        chain = EscalationChain([single])
        ep = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "Hello"}]
        with pytest.raises(MalformedOutputError, match="exhausted"):
            await ep.escalate_and_retry(messages)

    async def test_generate_with_malformed_recovery_first_attempt(self) -> None:
        """generate_with_malformed_recovery is a plain generate on step 1."""
        primary = _mock_provider(content="First try")
        chain = EscalationChain([primary])
        ep = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "Go"}]
        result = await ep.generate_with_malformed_recovery(messages)
        assert result.content == "First try"
