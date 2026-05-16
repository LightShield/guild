"""Tests for knowledge/temporal.py — temporal knowledge management (REQ-27)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.knowledge.temporal import TemporalKnowledge
from guild.storage.sqlite import Storage
from guild.storage.audit import DecisionRecord
from guild.storage.learnings import LearningRecord



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
class TestDecisionHistory:
    """Decision history retrieval."""

    async def test_get_decision_history(self, storage: Storage, guild_dir: Path) -> None:
        """Decisions are returned in reverse chronological order."""
        await storage.log_decision(
            DecisionRecord(task_id="t1",
            agent_id="a1",
            decision="Use SQLite",
            rationale="Simple, no server needed",)
        )
        await storage.log_decision(
            DecisionRecord(task_id="t1",
            agent_id="a1",
            decision="Use async",
            rationale="Non-blocking I/O",)
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
class TestRelevantContext:
    """Assembling relevant temporal context for tasks."""

    async def test_get_relevant_context_includes_learnings(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """Learnings with sufficient confidence appear in context."""
        # Add a high-confidence learning
        await storage.add_learning(
            LearningRecord(category="pattern",
            content="Use dataclasses for internal data",
            confidence=0.8,)
        )
        # Add a low-confidence learning (should not appear)
        await storage.add_learning(
            LearningRecord(category="tool_tip",
            content="Try ruff for linting",
            confidence=0.2,)
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


# ------------------------------------------------------------------
# REQ-27.2: Present state + key past info fetchable when relevant
# ------------------------------------------------------------------


@pytest.mark.unit
class TestPresentStateAndPastInfo:
    """Tests for get_present_state and get_key_past_info."""

    async def test_get_present_state_includes_git_status(
        self, storage: Storage, guild_dir: Path, tmp_path: Path
    ) -> None:
        """get_present_state includes git status output for a git repo."""
        import subprocess

        # Create a mini git repo in tmp_path
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        # Create a file and commit
        (repo_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        # Create an uncommitted change
        (repo_dir / "new.txt").write_text("world")

        tk = TemporalKnowledge(guild_dir, storage)
        result = await tk.get_present_state(str(repo_dir))

        assert "Present State" in result
        assert "Git Status" in result
        # The new untracked file should show up
        assert "new.txt" in result

    async def test_get_key_past_info_fetches_relevant_context(
        self, storage: Storage, guild_dir: Path
    ) -> None:
        """get_key_past_info returns decisions and learnings."""
        # Add a decision
        await storage.log_decision(
            DecisionRecord(task_id="t1",
            agent_id="a1",
            decision="Use async patterns",
            rationale="Better I/O performance",)
        )
        # Add a high-confidence learning
        await storage.add_learning(
            LearningRecord(category="pattern",
            content="Always validate inputs",
            confidence=0.9,)
        )

        tk = TemporalKnowledge(guild_dir, storage)
        result = await tk.get_key_past_info("Implement validation")

        assert "Key Past Info" in result
        assert "Use async patterns" in result
        assert "Always validate inputs" in result


# ======================================================================
# Temporal knowledge edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestTemporalKnowledgeEdgeCases:
    """Cover temporal knowledge assembly edge cases."""

    async def test_get_relevant_context_no_instructions(self, tmp_path: Path) -> None:
        """get_relevant_context works when no prompt.md exists."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_relevant_context("test task")
        # No instructions, no decisions, no learnings => empty string
        assert result == ""
        await store.close()

    async def test_get_relevant_context_with_instructions(self, tmp_path: Path) -> None:
        """get_relevant_context includes prompt.md content."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "prompt.md").write_text("# Custom Instructions\nDo X.")

        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_relevant_context("test task")
        assert "Project Instructions" in result
        assert "Custom Instructions" in result
        await store.close()

    async def test_get_present_state_with_git(self, tmp_path: Path) -> None:
        """get_present_state runs git commands successfully."""
        import subprocess

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        # Create a mini git repo for testing
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        (repo_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        result = await tk.get_present_state(str(repo_dir))
        assert "Present State" in result
        await store.close()

    async def test_get_present_state_nonexistent_dir(self, tmp_path: Path) -> None:
        """get_present_state handles failure gracefully when commands fail."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_present_state("/nonexistent/path/xyz")
        assert "No project state" in result
        await store.close()

    async def test_get_key_past_info_empty(self, tmp_path: Path) -> None:
        """get_key_past_info returns empty when no data."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_key_past_info("test task")
        assert result == ""
        await store.close()


# ======================================================================
# Temporal knowledge branches (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestTemporalKnowledgeBranches:
    """Cover temporal knowledge uncovered branches."""

    async def test_format_decisions_called_in_context(self, tmp_path: Path) -> None:
        """get_relevant_context formats decisions when they exist (lines 68-69)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        # Add decisions so lines 68-69 are hit
        await store.log_decision(
            DecisionRecord(task_id="t1",
            agent_id="a1",
            decision="Use pattern X",
            rationale="It is efficient",)
        )

        tk = TemporalKnowledge(guild_dir, store)
        context = await tk.get_relevant_context("some task")
        assert "Use pattern X" in context
        assert "Recent Decisions" in context
        await store.close()

    async def test_run_cmd_returns_none_on_failure(self, tmp_path: Path) -> None:
        """_run_cmd returns None when command fails (line 163->167)."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, store)

        # Run a command that will fail (non-existent dir)
        result = await tk._run_cmd("git status", "/nonexistent/path/xyz")
        assert result is None
        await store.close()

    async def test_present_state_no_git_repo(self, tmp_path: Path) -> None:
        """get_present_state in a non-git dir returns \'No project state\'."""
        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        # Use a directory that is NOT a git repo and has no ls
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, store)
        # git commands will fail, ls will succeed
        result = await tk.get_present_state(str(empty_dir))
        # At minimum the ls command should work
        assert "Present State" in result or "No project state" in result
        await store.close()

    async def test_run_cmd_returns_none_on_timeout(self, tmp_path: Path) -> None:
        """_run_cmd returns None when command times out (line 174)."""
        from unittest.mock import patch

        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, store)

        with patch("guild.knowledge.temporal.asyncio.wait_for", side_effect=TimeoutError()):
            result = await tk._run_cmd("sleep 100", str(tmp_path))
        assert result is None
        await store.close()
