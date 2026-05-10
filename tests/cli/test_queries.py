"""Tests for cli/queries.py — database query helpers (REQ-06.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.cli.queries import (
    fetch_audit,
    fetch_decisions,
    fetch_learnings,
    fetch_task_history,
    fetch_task_messages,
    fetch_token_summary,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_mock_storage(**method_returns: object) -> MagicMock:
    """Create a mock Storage that works as an async context manager."""
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    for method, retval in method_returns.items():
        setattr(mock, method, AsyncMock(return_value=retval))
    return mock


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestFetchAudit:
    """fetch_audit reads audit entries from storage."""

    async def test_returns_audit_entries(self, tmp_path: Path) -> None:
        """fetch_audit returns entries from storage."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        mock_store = _make_mock_storage(list_audit=[{"action": "task_completed"}])

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_audit(db_path, limit=10)

        assert result == [{"action": "task_completed"}]
        mock_store.list_audit.assert_awaited_once_with(limit=10)

    async def test_returns_empty_for_missing_db(self, tmp_path: Path) -> None:
        """fetch_audit returns [] when the database file does not exist."""
        db_path = tmp_path / "nonexistent.db"
        result = await fetch_audit(db_path, limit=10)
        assert result == []


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestFetchDecisions:
    """fetch_decisions reads decision log entries."""

    async def test_returns_decisions(self, tmp_path: Path) -> None:
        """fetch_decisions returns decisions from storage."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        mock_store = _make_mock_storage(list_decisions=[{"decision": "approve"}])

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_decisions(db_path, task_id=None, limit=5)

        assert result == [{"decision": "approve"}]

    async def test_passes_task_id_filter(self, tmp_path: Path) -> None:
        """fetch_decisions forwards task_id to storage."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        mock_store = _make_mock_storage(list_decisions=[])

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            await fetch_decisions(db_path, task_id="task-42", limit=10)

        mock_store.list_decisions.assert_awaited_once_with(task_id="task-42", limit=10)


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestFetchTaskHistory:
    """fetch_task_history reads and sorts tasks."""

    async def test_returns_most_recent_first(self, tmp_path: Path) -> None:
        """Tasks are sorted by created_at descending."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        tasks = [
            {"task_id": "old", "created_at": "2025-01-01"},
            {"task_id": "new", "created_at": "2025-06-01"},
        ]
        mock_store = _make_mock_storage(list_tasks=tasks)

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_task_history(db_path, limit=10, status=None)

        assert result[0]["task_id"] == "new"

    async def test_limit_caps_results(self, tmp_path: Path) -> None:
        """Only 'limit' tasks are returned."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        tasks = [
            {"task_id": f"t-{i}", "created_at": f"2025-0{i + 1}-01"}
            for i in range(5)
        ]
        mock_store = _make_mock_storage(list_tasks=tasks)

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_task_history(db_path, limit=2, status=None)

        assert len(result) == 2


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestFetchTokenSummary:
    """fetch_token_summary reads token usage."""

    async def test_returns_summary_dict(self, tmp_path: Path) -> None:
        """fetch_token_summary returns the summary dict from storage."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        summary = {"total_input": 1000, "total_output": 500}
        mock_store = _make_mock_storage(get_token_summary=summary)

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_token_summary(db_path)

        assert result == summary

    async def test_returns_none_for_missing_db(self, tmp_path: Path) -> None:
        """fetch_token_summary returns None when db is missing."""
        db_path = tmp_path / "nonexistent.db"
        result = await fetch_token_summary(db_path)
        assert result is None


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestFetchTaskMessages:
    """fetch_task_messages retrieves messages for a task's agent."""

    async def test_returns_empty_for_nonexistent_task(self, tmp_path: Path) -> None:
        """Returns [] when the task does not exist."""
        guild_dir = tmp_path
        db_path = guild_dir / "guild.db"
        db_path.touch()
        mock_store = _make_mock_storage(get_task=None)

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_task_messages(guild_dir, "no-such-task")

        assert result == []


@pytest.mark.unit
@pytest.mark.req("REQ-09.4")
class TestFetchLearnings:
    """fetch_learnings reads learning entries."""

    async def test_returns_learnings(self, tmp_path: Path) -> None:
        """fetch_learnings returns entries from storage."""
        db_path = tmp_path / "guild.db"
        db_path.touch()
        learnings = [{"id": 1, "category": "pattern", "content": "use async"}]
        mock_store = _make_mock_storage(list_learnings=learnings)

        with patch("guild.storage.sqlite.Storage", return_value=mock_store):
            result = await fetch_learnings(db_path, category="pattern", limit=10)

        assert result == learnings
        mock_store.list_learnings.assert_awaited_once_with(category="pattern", limit=10)

    async def test_returns_empty_for_missing_db(self, tmp_path: Path) -> None:
        """Returns [] when the db file is absent."""
        db_path = tmp_path / "nonexistent.db"
        result = await fetch_learnings(db_path, category=None, limit=10)
        assert result == []
