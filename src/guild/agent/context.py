"""Multi-tier context compression for agent message history (REQ-07.4, REQ-07.8, REQ-07.10)."""

from __future__ import annotations

import copy

__all__ = [
    "CHARS_PER_TOKEN",
    "ContextManager",
    "MIN_CONTENT_LEN",
    "TRUNCATION_MARKER",
]

CHARS_PER_TOKEN = 4
TRUNCATION_MARKER = "\n...[truncated]..."
MIN_CONTENT_LEN = 50


class ContextManager:
    """Multi-tier context compression for agent message history.

    Supports:
    - Tier 1 (MicroCompact): local trim of old tool outputs
    - Structured handoff for context resets
    - Static/dynamic prompt separation for cache efficiency
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        preserve_recent: int = 4,
        compact_threshold: float = 0.7,
    ) -> None:
        self.max_tokens = max_tokens
        self.preserve_recent = preserve_recent
        self.compact_threshold = compact_threshold

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Estimate token count from message content length."""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if content:
                total_chars += len(content)
        return total_chars // CHARS_PER_TOKEN

    def needs_compaction(self, messages: list[dict]) -> bool:
        """Check if messages exceed the compact threshold."""
        threshold_tokens = int(self.max_tokens * self.compact_threshold)
        return self.estimate_tokens(messages) >= threshold_tokens

    def compact(self, messages: list[dict]) -> list[dict]:
        """Tier 1: MicroCompact -- local trim of old tool outputs.

        Strategy: preserve system prompt + recent N messages fully.
        Truncate old tool outputs (oldest first, most aggressively).
        Never removes messages -- only shortens content.
        """
        if not messages:
            return []

        result = copy.deepcopy(messages)
        threshold_tokens = int(self.max_tokens * self.compact_threshold)

        # Identify protected indices: system prompt (index 0) and recent N
        protected = self._protected_indices(result)

        # Truncate old tool outputs, oldest first, most aggressively
        trimmable = [
            i for i in range(len(result))
            if i not in protected and result[i].get("role") == "tool"
        ]

        for idx in trimmable:
            if self.estimate_tokens(result) <= threshold_tokens:
                break
            result[idx] = self._truncate_message(result[idx])

        return result

    def create_handoff_artifact(
        self,
        messages: list[dict],
        task_description: str,
    ) -> str:
        """Create a structured handoff for context reset (REQ-07.8).

        Returns a summary artifact that captures:
        - Original task
        - Key decisions made
        - Current state (what's been done)
        - What remains to do
        """
        decisions = self._extract_decisions(messages)
        completed = self._extract_completed_actions(messages)

        lines = [
            "## Context Handoff",
            "",
            f"### Task\n{task_description}",
            "",
            "### Key Decisions",
        ]
        if decisions:
            for d in decisions:
                lines.append(f"- {d}")
        else:
            lines.append("- (none recorded)")

        lines.append("")
        lines.append("### Completed Actions")
        if completed:
            for c in completed:
                lines.append(f"- {c}")
        else:
            lines.append("- (none recorded)")

        lines.append("")
        lines.append("### Remaining Work")
        lines.append("- Continue from where the previous context left off")

        return "\n".join(lines)

    @staticmethod
    def separate_static_dynamic(
        system_prompt: str,
        learnings: str,
        task: str,
    ) -> tuple[str, str]:
        """Separate static (cacheable) from dynamic content (REQ-07.10).

        Returns (static_part, dynamic_part).
        Static: system prompt (doesn't change between turns)
        Dynamic: learnings + task-specific context (changes per session)
        """
        static_part = system_prompt
        dynamic_part = ""
        if learnings:
            dynamic_part += f"## Learnings\n{learnings}\n\n"
        if task:
            dynamic_part += f"## Current Task\n{task}"
        return static_part, dynamic_part.strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _protected_indices(self, messages: list[dict]) -> set[int]:
        """Return indices that must not be truncated."""
        protected: set[int] = set()
        # Always protect system prompt (first message if role=system)
        if messages and messages[0].get("role") == "system":
            protected.add(0)
        # Protect recent N messages
        total = len(messages)
        start = max(0, total - self.preserve_recent)
        for i in range(start, total):
            protected.add(i)
        return protected

    def _truncate_message(self, msg: dict) -> dict:
        """Truncate a message's content to MIN_CONTENT_LEN + marker."""
        content = msg.get("content", "")
        if len(content) <= MIN_CONTENT_LEN:
            return msg
        msg["content"] = content[:MIN_CONTENT_LEN] + TRUNCATION_MARKER
        return msg

    def _extract_decisions(self, messages: list[dict]) -> list[str]:
        """Extract decision-like statements from assistant messages."""
        decisions: list[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            for line in content.split("\n"):
                lower = line.lower().strip()
                if lower.startswith("decision:") or lower.startswith("decided:"):
                    decisions.append(line.strip())
        return decisions

    def _extract_completed_actions(self, messages: list[dict]) -> list[str]:
        """Extract completed tool actions from tool messages."""
        actions: list[str] = []
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            # Use first line as summary of what was done
            first_line = content.split("\n")[0].strip()
            if first_line:
                actions.append(first_line[:100])
        return actions
