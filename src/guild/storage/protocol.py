"""Storage protocol — structural typing interface for storage backends.

Defines the minimum contract that any storage implementation must satisfy.
The concrete ``Storage`` class in ``sqlite.py`` is structurally compatible
with this protocol without needing to inherit from it, enabling future
backend swapping (e.g. PostgreSQL, DynamoDB) without changing call-sites.

Usage for type annotations::

    from guild.storage.protocol import StorageProtocol

    async def my_function(store: StorageProtocol) -> None:
        tasks = await store.list_tasks()
        ...
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["StorageProtocol"]


@runtime_checkable
class StorageProtocol(Protocol):
    """Structural interface for Guild storage backends."""

    async def connect(self) -> None:
        """Open the storage connection."""
        ...

    async def close(self) -> None:
        """Close the storage connection."""
        ...

    # Tasks
    async def create_task(self, task_id: str, description: str) -> None:
        """Create a new task record."""
        ...

    async def get_task(self, task_id: str) -> dict | None:
        """Retrieve a task by ID, or None if not found."""
        ...

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        """List tasks, optionally filtered by status."""
        ...

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update fields on an existing task."""
        ...

    # Agents
    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent with its block type."""
        ...

    async def list_agents(self) -> list[dict]:
        """List all registered agents."""
        ...

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update fields on an existing agent."""
        ...

    # Messages
    async def append_message(
        self, agent_id: str, role: str, content: str, **kwargs: str
    ) -> None:
        """Append a message to an agent's conversation history."""
        ...

    async def get_messages(self, agent_id: str) -> list[dict]:
        """Retrieve all messages for an agent."""
        ...

    # Audit
    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Write an entry to the audit log."""
        ...

    async def list_audit(self, limit: int = 50) -> list[dict]:
        """Retrieve recent audit log entries."""
        ...

    # Learnings
    async def add_learning(
        self,
        category: str,
        content: str,
        confidence: float = 0.3,
        scope: str | None = None,
        source_task_id: str | None = None,
    ) -> int:
        """Store a new learning and return its ID."""
        ...

    async def list_learnings(
        self,
        min_confidence: float = 0.0,
        category: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve learnings filtered by confidence, category, or scope."""
        ...

    # Token usage
    async def get_token_summary(self) -> dict:
        """Return aggregate token usage statistics."""
        ...

    # Checkpoints
    async def save_checkpoint(
        self, agent_id: str, task_id: str | None, state_json: str
    ) -> None:
        """Persist a checkpoint for an agent."""
        ...

    async def load_checkpoint(self, agent_id: str) -> dict | None:
        """Load the latest checkpoint for an agent, or None."""
        ...
