"""Checkpoint and resume for long-running agent tasks (REQ-07.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

from guild.agent.message import Message

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.agent.loop import AgentLoop
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = [
    "Checkpoint",
    "load_checkpoint",
    "recover_from_checkpoint",
    "save_checkpoint",
]

logger = get_logger(__name__)


@dataclass
class Checkpoint:
    """Serializable agent state for pause/resume."""

    agent_id: str
    task_id: str | None
    messages: list[Message]
    turn_number: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_calls: int

    def to_json(self) -> str:
        """Serialize checkpoint to JSON string."""
        data: dict[str, Any] = {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "messages": [m.to_dict() for m in self.messages],
            "turn_number": self.turn_number,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, data: str) -> Checkpoint:
        """Deserialize checkpoint from JSON string."""
        parsed = json.loads(data)
        return cls(
            agent_id=parsed["agent_id"],
            task_id=parsed["task_id"],
            messages=[Message.from_dict(m) for m in parsed["messages"]],
            turn_number=parsed["turn_number"],
            total_input_tokens=parsed["total_input_tokens"],
            total_output_tokens=parsed["total_output_tokens"],
            total_tool_calls=parsed["total_tool_calls"],
        )


async def save_checkpoint(storage: Storage, checkpoint: Checkpoint) -> None:
    """Persist a checkpoint to storage."""
    await storage.save_checkpoint(
        agent_id=checkpoint.agent_id,
        task_id=checkpoint.task_id,
        state_json=checkpoint.to_json(),
    )
    logger.debug("Saved checkpoint for agent %s", checkpoint.agent_id)


async def load_checkpoint(storage: Storage, agent_id: str) -> Checkpoint | None:
    """Load the most recent checkpoint for an agent."""
    row = await storage.load_checkpoint(agent_id)
    if row is None:
        return None
    return Checkpoint.from_json(row["state_json"])


async def recover_from_checkpoint(
    storage: Storage,
    agent_id: str,
    provider: LLMProvider,
    tool_executors: dict[str, Any],
    working_dir: str | None = None,
) -> AgentLoop | None:
    """Recover an agent loop from its last checkpoint.

    Loads the most recent checkpoint for the given agent and
    reconstructs an AgentLoop with the saved state. Returns None
    if no checkpoint exists.

    Args:
        storage: The storage backend.
        agent_id: The agent to recover.
        provider: The LLM provider instance.
        tool_executors: Dict of tool name to executor callable.
        working_dir: Working directory for tool execution.
    """
    from guild.agent.loop import DEFAULT_MAX_TURNS, AgentLoop, AgentLoopConfig

    checkpoint = await load_checkpoint(storage, agent_id)
    if checkpoint is None:
        return None

    loop = AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        config=AgentLoopConfig(working_dir=working_dir, max_turns=DEFAULT_MAX_TURNS),
    )

    # Messages are already Message objects from from_dict()
    loop.messages = list(checkpoint.messages)
    loop.total_input_tokens = checkpoint.total_input_tokens
    loop.total_output_tokens = checkpoint.total_output_tokens
    loop.total_tool_calls = checkpoint.total_tool_calls

    logger.info(
        "Recovered agent %s from checkpoint (turn %d)",
        agent_id,
        checkpoint.turn_number,
    )
    return loop
