"""Tests for cli/task_runner.py — task execution logic (REQ-06.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.agent.loop import DEFAULT_MAX_TURNS
from guild.cli.task_runner import (
    build_system_prompt_with_learnings,
    compute_max_turns,
    create_provider_for_backend,
)


@pytest.mark.unit
@pytest.mark.req("REQ-06.4")
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
@pytest.mark.req("REQ-06.4")
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
@pytest.mark.req("REQ-09.4")
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
            return_value=[
                {"category": "pattern", "content": "always use async", "confidence": 0.9}
            ]
        )

        with patch(
            "guild.agent.learning.format_learnings_for_injection",
            return_value="LEARNINGS:\n- always use async",
        ):
            result = await build_system_prompt_with_learnings(mock_store)

        assert "LEARNINGS" in result
        assert "always use async" in result
