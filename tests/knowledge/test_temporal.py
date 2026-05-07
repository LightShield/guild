"""Tests for knowledge/temporal.py — temporal knowledge management (REQ-27)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.knowledge.temporal import TemporalKnowledge
from guild.storage.sqlite import Storage


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def guild_dir(tmp_path: Path) -> Path:
    """Create a temporary .guild directory."""
    gd = tmp_path / ".guild"
    gd.mkdir()
    return gd


# ------------------------------------------------------------------
# REQ-27.1: Decision history
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-27.1")
class TestDecisionHistory:
    """Decision history retrieval."""

    async def test_get_decision_history(self, storage: Storage, guild_dir: Path) -> None:
        """Decisions are returned in reverse chronological order."""
        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use SQLite",
            rationale="Simple, no server needed",
        )
        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use async",
            rationale="Non-blocking I/O",
        )

        tk = TemporalKnowledge(guild_dir, storage)
        decisions = await tk.get_decision_history(limit=10)

        assert len(decisions) == 2
        # Most recent first
        assert decisions[0]["decision"] == "Use async"
        assert decisions[1]["decision"] == "Use SQLite"


# ------------------------------------------------------------------
# REQ-27.3: Project-level instruction files
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-27.3")
class TestProjectInstructions:
    """Loading .guild/prompt.md for project instructions."""

    async def test_get_project_instructions_reads_prompt_md(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """When prompt.md exists, its content is returned."""
        prompt_file = guild_dir / "prompt.md"
        prompt_file.write_text("Always write tests first.\nUse type hints.")

        tk = TemporalKnowledge(guild_dir, storage)
        result = await tk.get_project_instructions()

        assert result is not None
        assert "Always write tests first." in result
        assert "Use type hints." in result

    async def test_get_project_instructions_returns_none_when_missing(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """When prompt.md does not exist, None is returned."""
        tk = TemporalKnowledge(guild_dir, storage)
        result = await tk.get_project_instructions()

        assert result is None


# ------------------------------------------------------------------
# REQ-27.4: Learnings as temporal context
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-27.4")
class TestRelevantContext:
    """Assembling relevant temporal context for tasks."""

    async def test_get_relevant_context_includes_learnings(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """Learnings with sufficient confidence appear in context."""
        # Add a high-confidence learning
        await storage.add_learning(
            category="pattern",
            content="Use dataclasses for internal data",
            confidence=0.8,
        )
        # Add a low-confidence learning (should not appear)
        await storage.add_learning(
            category="tool_tip",
            content="Try ruff for linting",
            confidence=0.2,
        )

        tk = TemporalKnowledge(guild_dir, storage)
        context = await tk.get_relevant_context("Implement new feature")

        assert "Use dataclasses for internal data" in context
        assert "Try ruff for linting" not in context
        assert "Learnings from Past Tasks" in context

    async def test_get_relevant_context_includes_instructions(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """Project instructions from prompt.md appear in context."""
        prompt_file = guild_dir / "prompt.md"
        prompt_file.write_text("Follow TDD approach.")

        tk = TemporalKnowledge(guild_dir, storage)
        context = await tk.get_relevant_context("Build auth module")

        assert "Follow TDD approach." in context
        assert "Project Instructions" in context
