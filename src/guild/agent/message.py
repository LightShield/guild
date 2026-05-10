"""Typed message representation for agent conversation history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Message"]


@dataclass
class Message:
    """A single message in an agent conversation.

    Replaces raw ``dict[str, Any]`` message representations with a typed
    dataclass for better IDE support, validation, and readability.
    """

    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for provider/storage boundaries."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create a Message from a plain dict."""
        return cls(
            role=data.get("role", ""),
            content=data.get("content", ""),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
        )
