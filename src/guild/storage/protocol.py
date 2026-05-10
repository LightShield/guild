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

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    # Tasks
    async def create_task(self, task_id: str, description: str) -> None: ...

    async def get_task(self, task_id: str) -> dict | None: ...

    async def list_tasks(self, status: str | None = None) -> list[dict]: ...

    async def update_task(self, task_id: str, **fields: str) -> None: ...

    # Agents
    async def register_agent(self, agent_id: str, block_name: str) -> None: ...

    async def list_agents(self) -> list[dict]: ...

    async def update_agent(self, agent_id: str, **fields: str) -> None: ...

    # Messages
    async def append_message(
        self, agent_id: str, role: str, content: str, **kwargs: str
    ) -> None: ...

    async def get_messages(self, agent_id: str) -> list[dict]: ...

    # Audit
    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None: ...

    async def list_audit(self, limit: int = 50) -> list[dict]: ...

    # Learnings
    async def add_learning(
        self,
        category: str,
        content: str,
        confidence: float = 0.3,
        scope: str | None = None,
        source_task_id: str | None = None,
    ) -> int: ...

    async def list_learnings(
        self,
        min_confidence: float = 0.0,
        category: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict]: ...

    # Token usage
    async def get_token_summary(self) -> dict: ...

    # Checkpoints
    async def save_checkpoint(
        self, agent_id: str, task_id: str | None, state_json: str
    ) -> None: ...

    async def load_checkpoint(self, agent_id: str) -> dict | None: ...
