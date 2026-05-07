"""Tests for agent/checkpoint.py — checkpoint and resume (REQ-07.2, REQ-11.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.agent.checkpoint import (
    Checkpoint,
    load_checkpoint,
    recover_from_checkpoint,
    save_checkpoint,
)
from guild.storage.sqlite import Storage


def _sample_checkpoint() -> Checkpoint:
    """Create a sample checkpoint for testing."""
    return Checkpoint(
        agent_id="agent-001",
        task_id="task-abc",
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Fix the bug."},
            {"role": "assistant", "content": "I'll look into it."},
        ],
        turn_number=5,
        total_input_tokens=1200,
        total_output_tokens=800,
        total_tool_calls=3,
    )


@pytest.mark.unit
@pytest.mark.req("REQ-07.2")
class TestCheckpointSerialization:
    """Checkpoint JSON round-trip."""

    def test_checkpoint_serializes_to_json(self) -> None:
        """Checkpoint.to_json() produces valid JSON with all fields."""
        cp = _sample_checkpoint()
        json_str = cp.to_json()

        assert '"agent_id": "agent-001"' in json_str
        assert '"task_id": "task-abc"' in json_str
        assert '"turn_number": 5' in json_str
        assert '"total_input_tokens": 1200' in json_str
        assert '"total_output_tokens": 800' in json_str
        assert '"total_tool_calls": 3' in json_str

    def test_checkpoint_deserializes_from_json(self) -> None:
        """Checkpoint.from_json() restores all fields."""
        cp = _sample_checkpoint()
        json_str = cp.to_json()

        restored = Checkpoint.from_json(json_str)

        assert restored.agent_id == cp.agent_id
        assert restored.task_id == cp.task_id
        assert restored.messages == cp.messages
        assert restored.turn_number == cp.turn_number
        assert restored.total_input_tokens == cp.total_input_tokens
        assert restored.total_output_tokens == cp.total_output_tokens
        assert restored.total_tool_calls == cp.total_tool_calls

    def test_checkpoint_none_task_id(self) -> None:
        """Checkpoint with None task_id serializes and deserializes."""
        cp = Checkpoint(
            agent_id="a1",
            task_id=None,
            messages=[],
            turn_number=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tool_calls=0,
        )
        restored = Checkpoint.from_json(cp.to_json())
        assert restored.task_id is None


@pytest.mark.unit
@pytest.mark.req("REQ-07.2")
class TestCheckpointPersistence:
    """Checkpoint save/load with SQLite storage."""

    async def test_save_checkpoint_persists_to_storage(self, tmp_path: Path) -> None:
        """save_checkpoint writes to the checkpoints table."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            cp = _sample_checkpoint()
            await save_checkpoint(storage, cp)

            # Verify it was stored
            assert storage._db is not None
            cursor = await storage._db.execute(
                "SELECT state_json FROM checkpoints WHERE agent_id = ?",
                (cp.agent_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            restored = Checkpoint.from_json(row[0])
            assert restored.agent_id == cp.agent_id
            assert restored.turn_number == cp.turn_number
        finally:
            await storage.close()

    async def test_load_checkpoint_returns_latest(self, tmp_path: Path) -> None:
        """load_checkpoint returns the most recently saved checkpoint."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            cp1 = Checkpoint(
                agent_id="agent-001",
                task_id="task-1",
                messages=[{"role": "user", "content": "first"}],
                turn_number=2,
                total_input_tokens=100,
                total_output_tokens=50,
                total_tool_calls=1,
            )
            cp2 = Checkpoint(
                agent_id="agent-001",
                task_id="task-1",
                messages=[{"role": "user", "content": "second"}],
                turn_number=7,
                total_input_tokens=500,
                total_output_tokens=300,
                total_tool_calls=4,
            )
            await save_checkpoint(storage, cp1)
            await save_checkpoint(storage, cp2)

            loaded = await load_checkpoint(storage, "agent-001")
            assert loaded is not None
            assert loaded.turn_number == 7
            assert loaded.messages == [{"role": "user", "content": "second"}]
        finally:
            await storage.close()

    async def test_load_checkpoint_returns_none_when_missing(self, tmp_path: Path) -> None:
        """load_checkpoint returns None for an agent with no checkpoints."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            result = await load_checkpoint(storage, "nonexistent-agent")
            assert result is None
        finally:
            await storage.close()


@pytest.mark.unit
@pytest.mark.req("REQ-11.4")
class TestRecoverFromCheckpoint:
    """Error recovery — restart crashed agents from last checkpoint."""

    async def test_recover_from_checkpoint_restores_state(self, tmp_path: Path) -> None:
        """recover_from_checkpoint reconstructs AgentLoop with saved state."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            cp = Checkpoint(
                agent_id="agent-crash",
                task_id="task-42",
                messages=[
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Fix the bug."},
                    {"role": "assistant", "content": "Working on it."},
                ],
                turn_number=3,
                total_input_tokens=500,
                total_output_tokens=300,
                total_tool_calls=2,
            )
            await save_checkpoint(storage, cp)

            provider = AsyncMock()
            tool_executors = {"file_read": AsyncMock()}

            loop = await recover_from_checkpoint(
                storage, "agent-crash", provider, tool_executors, "/tmp"
            )

            assert loop is not None
            # Verify state was restored
            from guild.agent.loop import AgentLoop

            assert isinstance(loop, AgentLoop)
            assert loop.messages == cp.messages
            assert loop.total_input_tokens == 500
            assert loop.total_output_tokens == 300
            assert loop.total_tool_calls == 2
            assert loop.working_dir == "/tmp"
        finally:
            await storage.close()

    async def test_recover_returns_none_when_no_checkpoint(self, tmp_path: Path) -> None:
        """recover_from_checkpoint returns None if no checkpoint exists."""
        storage = Storage(tmp_path / "test.db")
        await storage.connect()
        try:
            provider = AsyncMock()
            tool_executors = {}

            result = await recover_from_checkpoint(
                storage, "no-such-agent", provider, tool_executors
            )

            assert result is None
        finally:
            await storage.close()
