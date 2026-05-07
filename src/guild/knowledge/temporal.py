"""Temporal knowledge management — decisions, learnings, instructions (REQ-27).

Assembles contextual knowledge from project instructions, past decisions,
and learnings for injection into agent prompts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from guild.storage.sqlite import Storage

__all__ = ["TemporalKnowledge"]

logger = logging.getLogger(__name__)


class TemporalKnowledge:
    """Manages temporal context: decisions, learnings, project instructions.

    Provides methods to load and assemble contextual knowledge for
    agent tasks from multiple sources.
    """

    def __init__(self, guild_dir: Path, storage: Storage) -> None:
        self._guild_dir = guild_dir
        self._storage = storage

    async def get_project_instructions(self) -> str | None:
        """Load .guild/prompt.md if it exists (REQ-27.3).

        Returns the file content as a string, or None if the file
        does not exist.
        """
        prompt_file = self._guild_dir / "prompt.md"
        if prompt_file.is_file():
            return prompt_file.read_text()
        return None

    async def get_decision_history(self, limit: int = 20) -> list[dict]:
        """Get recent decisions with rationale (REQ-27.1).

        Returns decisions ordered most-recent-first, up to limit.
        """
        return await self._storage.list_decisions(limit=limit)

    async def get_relevant_context(self, task_description: str) -> str:
        """Assemble relevant temporal context for a task (REQ-27.1, 27.4).

        Combines: project instructions + recent decisions + relevant
        learnings into a single context string for agent injection.
        """
        sections: list[str] = []

        # REQ-27.3: Project instructions
        instructions = await self.get_project_instructions()
        if instructions:
            sections.append(f"## Project Instructions\n\n{instructions}")

        # REQ-27.1: Recent decisions
        decisions = await self.get_decision_history(limit=10)
        if decisions:
            decision_lines = self._format_decisions(decisions)
            sections.append(f"## Recent Decisions\n\n{decision_lines}")

        # REQ-27.4: Relevant learnings
        learnings = await self._storage.list_learnings(min_confidence=0.5)
        if learnings:
            learning_lines = self._format_learnings(learnings)
            sections.append(f"## Learnings from Past Tasks\n\n{learning_lines}")

        if not sections:
            return ""

        return "\n\n".join(sections)

    def _format_decisions(self, decisions: list[dict]) -> str:
        """Format decision records into readable context."""
        lines: list[str] = []
        for d in decisions[:10]:
            decision_text = d.get("decision", "")
            rationale = d.get("rationale", "")
            lines.append(f"- {decision_text}: {rationale}")
        return "\n".join(lines)

    def _format_learnings(self, learnings: list[dict]) -> str:
        """Format learning records into readable context."""
        lines: list[str] = []
        for item in learnings[:10]:
            category = item.get("category", "unknown")
            content = item.get("content", "")
            confidence = item.get("confidence", 0)
            lines.append(f"- [{category}] (confidence: {confidence:.1f}) {content}")
        return "\n".join(lines)
