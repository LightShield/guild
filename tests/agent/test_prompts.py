"""Tests for agent/prompts.py — shared system prompts (REQ-06.2)."""

from __future__ import annotations

import pytest

from guild.agent.prompts import GUILD_MASTER_PROMPT


@pytest.mark.unit
@pytest.mark.req("REQ-06.8")
class TestGuildMasterPrompt:
    """GUILD_MASTER_PROMPT is well-formed and usable as a system prompt."""

    def test_prompt_is_non_empty_string(self) -> None:
        """The prompt must be a non-empty string."""
        assert isinstance(GUILD_MASTER_PROMPT, str)
        assert len(GUILD_MASTER_PROMPT) > 0

    def test_prompt_contains_role_statement(self) -> None:
        """The prompt tells the agent what it is."""
        assert "agent" in GUILD_MASTER_PROMPT.lower()

    def test_prompt_contains_tool_usage_instruction(self) -> None:
        """The prompt instructs the agent to use tools."""
        lower = GUILD_MASTER_PROMPT.lower()
        assert "tool" in lower

    def test_prompt_mentions_available_tools(self) -> None:
        """The prompt lists the standard tools by name."""
        assert "file_read" in GUILD_MASTER_PROMPT
        assert "file_write" in GUILD_MASTER_PROMPT
        assert "shell" in GUILD_MASTER_PROMPT

    def test_prompt_is_exported_in_all(self) -> None:
        """GUILD_MASTER_PROMPT is in the module's __all__."""
        import guild.agent.prompts as mod

        assert "GUILD_MASTER_PROMPT" in mod.__all__
