"""Tests for cli/task_runner.py — task execution logic (REQ-06.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.agent.loop import DEFAULT_MAX_TURNS
from guild.cli.task_runner import (
    build_system_prompt_with_learnings,
    compute_max_turns,
    create_provider_for_backend,
    create_resilient_provider,
    persist_task_result,
    run_task,
    run_team_task,
)


@pytest.mark.unit
class TestComputeMaxTurns:
    """compute_max_turns converts timeout seconds to a turn count."""

    def test_zero_timeout_returns_default(self) -> None:
        """A zero timeout falls back to DEFAULT_MAX_TURNS."""
        assert compute_max_turns(0) == DEFAULT_MAX_TURNS

    def test_negative_timeout_returns_default(self) -> None:
        """A negative timeout falls back to DEFAULT_MAX_TURNS."""
        assert compute_max_turns(-10) == DEFAULT_MAX_TURNS

    def test_short_timeout_returns_minimum(self) -> None:
        """A very short timeout returns the minimum turn count (5)."""
        result = compute_max_turns(10)
        assert result == 5

    def test_long_timeout_returns_capped(self) -> None:
        """A very large timeout caps at 200 turns."""
        result = compute_max_turns(100_000)
        assert result == 200

    def test_moderate_timeout_scales_proportionally(self) -> None:
        """A moderate timeout produces proportional turns."""
        result = compute_max_turns(100)
        # 100 / 10 = 10, within [5, 200]
        assert result == 10

    def test_exact_boundary_values(self) -> None:
        """Boundary: 50s => 5 (min), 2000s => 200 (cap)."""
        assert compute_max_turns(50) == 5
        assert compute_max_turns(2000) == 200


@pytest.mark.unit
class TestCreateProviderForBackend:
    """create_provider_for_backend dispatches to the correct backend."""

    @patch("guild.cli.task_runner.create_provider_for_backend.__module__", "guild.cli.task_runner")
    def test_unknown_provider_raises_value_error(self) -> None:
        """An unknown provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider_for_backend("nonexistent", "http://localhost", "model")

    @patch("guild.provider.ollama.create_provider")
    def test_ollama_provider_dispatches_correctly(self, mock_create: MagicMock) -> None:
        """The 'ollama' backend delegates to ollama.create_provider."""
        mock_create.return_value = MagicMock()
        result = create_provider_for_backend("ollama", "http://localhost:11434", "llama3")
        mock_create.assert_called_once_with("http://localhost:11434", "llama3")
        assert result is mock_create.return_value


@pytest.mark.unit
class TestBuildSystemPromptWithLearnings:
    """build_system_prompt_with_learnings injects learnings into the system prompt."""

    async def test_base_prompt_returned_when_no_learnings(self) -> None:
        """Without any learnings the base GUILD_MASTER_PROMPT is returned."""
        mock_store = MagicMock()
        mock_store.list_learnings = AsyncMock(return_value=[])

        result = await build_system_prompt_with_learnings(mock_store)

        from guild.agent.prompts import GUILD_MASTER_PROMPT

        assert result == GUILD_MASTER_PROMPT

    async def test_learnings_appended_to_prompt(self) -> None:
        """High-confidence learnings are appended to the system prompt."""
        mock_store = MagicMock()
        mock_store.list_learnings = AsyncMock(
            return_value=[{"category": "pattern", "content": "always use async", "confidence": 0.9}]
        )

        with patch(
            "guild.agent.learning.format_learnings_for_injection",
            return_value="LEARNINGS:\n- always use async",
        ):
            result = await build_system_prompt_with_learnings(mock_store)

        assert "LEARNINGS" in result
        assert "always use async" in result


@pytest.mark.unit
class TestCreateResilientProvider:
    """create_resilient_provider builds providers with escalation and retry."""

    def test_empty_provider_name_raises(self) -> None:
        """An empty provider_name raises ValueError (line 90)."""
        config = MagicMock()
        config.provider_name = ""

        with pytest.raises(ValueError, match="provider_name must be configured"):
            create_resilient_provider(config)

    @patch("guild.cli.task_runner.create_provider_for_backend")
    def test_no_escalation_returns_retry_provider(self, mock_create: MagicMock) -> None:
        """When no escalation chain is configured, a plain RetryProvider wraps the primary."""
        mock_create.return_value = MagicMock()
        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "llama3"
        config.escalation_chain = ""
        config.escalation_cli_providers = ""

        result = create_resilient_provider(config)

        from guild.provider.retry import RetryProvider

        assert isinstance(result, RetryProvider)

    @patch("guild.cli.task_runner.create_provider_for_backend")
    def test_escalation_chain_with_models(self, mock_create: MagicMock) -> None:
        """Escalation chain models build an EscalatingProvider (lines 100-113)."""
        primary = MagicMock(name="primary")
        fallback = MagicMock(name="fallback")
        mock_create.side_effect = [primary, fallback]

        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "llama3"
        config.escalation_chain = "llama3,mistral"
        config.escalation_cli_providers = ""

        result = create_resilient_provider(config)

        from guild.provider.retry import RetryProvider

        assert isinstance(result, RetryProvider)
        # Two calls: primary (llama3) + fallback (mistral)
        assert mock_create.call_count == 2

    @patch("guild.provider.cli_provider.CLIToolProvider")
    @patch("guild.cli.task_runner.create_provider_for_backend")
    def test_escalation_chain_with_cli_tools(
        self, mock_create: MagicMock, mock_cli: MagicMock
    ) -> None:
        """CLI tool providers are appended to the escalation chain (lines 106-110)."""
        mock_create.return_value = MagicMock()
        mock_cli.return_value = MagicMock()

        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "llama3"
        config.escalation_chain = ""
        config.escalation_cli_providers = "my_tool"

        result = create_resilient_provider(config)

        from guild.provider.retry import RetryProvider

        assert isinstance(result, RetryProvider)
        mock_cli.assert_called_once_with(command="my_tool")

    @patch("guild.cli.task_runner.create_provider_for_backend")
    def test_escalation_chain_skips_duplicate_model(self, mock_create: MagicMock) -> None:
        """Escalation chain skips a model that matches the primary (line 101)."""
        primary = MagicMock(name="primary")
        mock_create.return_value = primary

        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "llama3"
        config.escalation_chain = "llama3"  # same as primary
        config.escalation_cli_providers = ""

        create_resilient_provider(config)

        # Only the primary is created; the duplicate is skipped
        assert mock_create.call_count == 1


@pytest.mark.unit
class TestRunTask:
    """run_task validates inputs and orchestrates the agent loop."""

    async def test_empty_description_raises(self, tmp_path) -> None:
        """An empty task description raises ValueError (line 161)."""
        config = MagicMock()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        with pytest.raises(ValueError, match="Task description cannot be empty"):
            await run_task(config, str(tmp_path), "", "autopilot", 0, guild_dir)

    async def test_whitespace_only_description_raises(self, tmp_path) -> None:
        """A whitespace-only task description raises ValueError (line 161)."""
        config = MagicMock()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        with pytest.raises(ValueError, match="Task description cannot be empty"):
            await run_task(config, str(tmp_path), "   ", "autopilot", 0, guild_dir)


@pytest.mark.unit
class TestPersistTaskResult:
    """persist_task_result saves task data and skips empty messages."""

    async def test_skips_message_with_no_role(self) -> None:
        """Messages without role are skipped (line 224->223 branch)."""
        mock_store = MagicMock()
        mock_store.create_task = AsyncMock()
        mock_store.update_task = AsyncMock()
        mock_store.register_agent = AsyncMock()
        mock_store.update_agent = AsyncMock()
        mock_store.append_message = AsyncMock()
        mock_store.log_audit = AsyncMock()

        # A message with no role should be skipped
        msg_no_role = MagicMock()
        msg_no_role.role = ""
        msg_no_role.content = "some content"

        msg_no_content = MagicMock()
        msg_no_content.role = "user"
        msg_no_content.content = ""

        msg_valid = MagicMock()
        msg_valid.role = "assistant"
        msg_valid.content = "hello"

        mock_loop = MagicMock()
        mock_loop.total_input_tokens = 100
        mock_loop.total_output_tokens = 50
        mock_loop.messages = [msg_no_role, msg_no_content, msg_valid]

        config = MagicMock()

        await persist_task_result(mock_store, mock_loop, "test task", "result", config)

        # Only the valid message should be appended
        assert mock_store.append_message.await_count == 1
        call_args = mock_store.append_message.await_args
        assert call_args[0][1] == "assistant"
        assert call_args[0][2] == "hello"


@pytest.mark.unit
class TestRunTeamTask:
    """run_team_task loads blocks and delegates to TeamRunner."""

    async def test_team_not_found_raises(self, tmp_path) -> None:
        """run_team_task raises ValueError when team is not found."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        blocks_dir = guild_dir / "blocks"
        blocks_dir.mkdir()

        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "test"
        config.escalation_chain = ""
        config.escalation_cli_providers = ""

        with (
            patch("guild.cli.task_runner.create_resilient_provider"),
            pytest.raises(ValueError, match="Team 'nonexistent' not found"),
        ):
            await run_team_task(config, str(tmp_path), guild_dir, "nonexistent", "do work")

    async def test_team_runs_successfully(self, tmp_path) -> None:
        """run_team_task runs a team and returns the result."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        blocks_dir = guild_dir / "blocks"
        blocks_dir.mkdir()

        config = MagicMock()
        config.provider_name = "ollama"
        config.base_url = "http://localhost:11434"
        config.model = "test"
        config.escalation_chain = ""
        config.escalation_cli_providers = ""

        mock_provider = MagicMock()
        mock_run = AsyncMock(return_value="team result")

        with (
            patch("guild.cli.task_runner.create_resilient_provider", return_value=mock_provider),
            patch("guild.orchestration.team_runner.TeamRunner.run", new=mock_run),
            patch("guild.blocks.registry.BlockRegistry.get_team") as mock_get_team,
        ):
            from guild.blocks.definition import TeamDef

            mock_get_team.return_value = TeamDef(
                name="test",
                blocks={"entry": "planner"},
                entry_block="entry",
            )
            result = await run_team_task(config, str(tmp_path), guild_dir, "test", "build feature")

        assert result == "team result"
