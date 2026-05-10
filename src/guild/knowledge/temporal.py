"""Temporal knowledge management — decisions, learnings, instructions (REQ-27).

Assembles contextual knowledge from project instructions, past decisions,
and learnings for injection into agent prompts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
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

    # ------------------------------------------------------------------
    # REQ-27.2: Present state + key past info fetchable when relevant
    # ------------------------------------------------------------------

    async def get_present_state(self, working_dir: str) -> str:
        """Get current project state summary (REQ-27.2).

        Includes git status, recent commits, and top-level file structure.
        """
        sections: list[str] = []

        git_status = await self._run_cmd("git status --short", working_dir)
        if git_status is not None:
            sections.append(f"### Git Status\n```\n{git_status}\n```")

        git_log = await self._run_cmd("git log --oneline -5", working_dir)
        if git_log is not None:
            sections.append(f"### Recent Commits\n```\n{git_log}\n```")

        ls_output = await self._run_cmd("ls -1", working_dir)
        if ls_output is not None:
            sections.append(f"### Top-Level Files\n```\n{ls_output}\n```")

        if not sections:
            return "No project state available."

        return "## Present State\n\n" + "\n\n".join(sections)

    async def get_key_past_info(self, task_description: str) -> str:
        """Fetch relevant historical context for a task (REQ-27.2).

        Returns recent decisions and learnings relevant to the task area.
        """
        sections: list[str] = []

        # Recent decisions
        decisions = await self.get_decision_history(limit=5)
        if decisions:
            formatted = self._format_decisions(decisions)
            sections.append(f"### Recent Decisions\n{formatted}")

        # Relevant learnings (high confidence only)
        learnings = await self._storage.list_learnings(min_confidence=0.5)
        if learnings:
            formatted = self._format_learnings(learnings)
            sections.append(f"### Relevant Learnings\n{formatted}")

        if not sections:
            return ""

        return "## Key Past Info\n\n" + "\n\n".join(sections)

    async def _run_cmd(self, cmd: str, cwd: str) -> str | None:
        """Run a shell command and return stdout, or None on failure.

        Uses create_subprocess_exec to avoid shell injection risks.
        These are internal git/ls commands for project state discovery,
        not user-initiated shell execution (the shell tool's denylist
        does not apply here).
        """
        timeout = 10  # seconds — git status/log should be fast
        try:
            argv = cmd.split()
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode == 0:
                return stdout.decode().strip()
        except TimeoutError:
            logger.debug("Command timed out: %s", cmd)
        except OSError:
            logger.debug("Command failed: %s", cmd)
        return None
