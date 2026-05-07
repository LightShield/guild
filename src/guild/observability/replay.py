"""Session replay from stored messages (REQ-11.2).

Provides the ability to replay and summarize past agent sessions
from the SQLite-backed message store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guild.storage.sqlite import Storage

__all__ = [
    "SessionReplay",
]


class SessionReplay:
    """Replay a past agent session from stored messages."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def get_session(self, agent_id: str) -> list[dict]:
        """Get all messages for an agent session in order."""
        return await self._storage.get_messages(agent_id)

    async def get_session_summary(self, agent_id: str) -> dict:
        """Get a summary of the session.

        Returns a dict with: turn_count, tool_calls, tools_used,
        message_count, and roles breakdown.
        """
        messages = await self._storage.get_messages(agent_id)
        if not messages:
            return {
                "turn_count": 0,
                "tool_calls": 0,
                "tools_used": [],
                "message_count": 0,
                "roles": {},
            }

        roles: dict[str, int] = {}
        tool_calls = 0
        tools_used: list[str] = []

        for msg in messages:
            role = msg.get("role", "unknown")
            roles[role] = roles.get(role, 0) + 1
            if role == "tool":
                tool_calls += 1
            # Extract tool names from tool_calls JSON
            raw_tool_calls = msg.get("tool_calls")
            if raw_tool_calls:
                self._extract_tool_names(raw_tool_calls, tools_used)

        # Turn count = number of assistant messages (each is one LLM turn)
        turn_count = roles.get("assistant", 0)

        return {
            "turn_count": turn_count,
            "tool_calls": tool_calls,
            "tools_used": sorted(set(tools_used)),
            "message_count": len(messages),
            "roles": roles,
        }

    def format_for_display(self, messages: list[dict]) -> str:
        """Format messages for human-readable replay output.

        Each message is formatted as:
        [ROLE] content
        ---
        """
        if not messages:
            return "(empty session)"

        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            # Truncate very long content for display
            display_content = content[:500] if len(content) > 500 else content
            lines.append(f"[{role}] {display_content}")
            lines.append("---")

        return "\n".join(lines)

    @staticmethod
    def _extract_tool_names(raw_tool_calls: str, tools_used: list[str]) -> None:
        """Extract tool names from a JSON tool_calls string."""
        import json

        try:
            calls = json.loads(raw_tool_calls)
            if isinstance(calls, list):
                for call in calls:
                    fn_info = call.get("function", {})
                    name = fn_info.get("name", "")
                    if name and name not in tools_used:
                        tools_used.append(name)
        except (json.JSONDecodeError, TypeError):
            pass
