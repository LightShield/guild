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

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.storage.sqlite import DecisionRecord, LearningRecord, QuestionRecord

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

    async def create_task(self, task_id: str, description: str) -> None:
        """Create a new task record."""
        ...

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a task by ID, or None if not found."""
        ...

    async def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List tasks, optionally filtered by status."""
        ...

    async def update_task(self, task_id: str, **fields: str) -> None:
        """Update fields on an existing task."""
        ...

    async def register_agent(self, agent_id: str, block_name: str) -> None:
        """Register a new agent with its block type."""
        ...

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        ...

    async def update_agent(self, agent_id: str, **fields: str) -> None:
        """Update fields on an existing agent."""
        ...

    async def append_message(self, agent_id: str, role: str, content: str, **kwargs: str) -> None:
        """Append a message to an agent's conversation history."""
        ...

    async def get_messages(self, agent_id: str) -> list[dict[str, Any]]:
        """Retrieve all messages for an agent."""
        ...

    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Write an entry to the audit log."""
        ...

    async def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent audit log entries."""
        ...

    async def log_decision(
        self,
        record: DecisionRecord | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        decision: str = "",
        rationale: str = "",
        alternatives: list[str] | None = None,
        *,
        reversible: bool = True,
    ) -> None:
        """Record a non-trivial decision with rationale."""
        ...

    async def add_learning(
        self,
        record: LearningRecord | None = None,
        category: str = "",
        content: str = "",
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
    ) -> list[dict[str, Any]]:
        """Retrieve learnings filtered by confidence, category, or scope."""
        ...

    async def get_token_summary(self) -> dict[str, Any]:
        """Return aggregate token usage statistics."""
        ...

    async def insert_question(
        self,
        record: QuestionRecord | None = None,
        question_id: str = "",
        question: str = "",
        context: str = "",
        created_at: str = "",
        task_id: str | None = None,
        agent_id: str | None = None,
        priority: str = "normal",
    ) -> None:
        """Insert a new question into the escalation queue."""
        ...

    async def save_checkpoint(self, agent_id: str, task_id: str | None, state_json: str) -> None:
        """Persist a checkpoint for an agent."""
        ...

    async def load_checkpoint(self, agent_id: str) -> dict[str, Any] | None:
        """Load the latest checkpoint for an agent, or None."""
        ...
