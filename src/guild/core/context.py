"""Context compression — MicroCompact (REQ-07.4).

Local trimming of old tool outputs to keep context within model limits.
Zero API calls — purely local string truncation.
"""

from __future__ import annotations

from guild.core.models import Message

__all__ = ["MicroCompact"]

CHARS_PER_TOKEN = 4
TRUNCATION_MARKER = "\n...[truncated]..."
MIN_CONTENT_LEN = 50


class MicroCompact:
    """Local context compressor that trims old tool outputs.

    Strategy: preserve system prompt and recent messages fully.
    Truncate old tool outputs (oldest first, most aggressively).
    Never removes messages — only shortens content.

    Args:
        max_tokens: Target maximum token count.
        preserve_recent: Number of recent message pairs to preserve fully.
    """

    def __init__(self, max_tokens: int = 8000, preserve_recent: int = 4) -> None:
        self._max_tokens = max_tokens
        self._preserve_recent = preserve_recent

    def compact(self, messages: list[Message]) -> list[Message]:
        """Compact messages to fit within token limit.

        Args:
            messages: Full conversation history.

        Returns:
            New list of messages with old tool outputs truncated.
        """
        if not messages:
            return []

        current_tokens = self._estimate_tokens(messages)
        if current_tokens <= self._max_tokens:
            return list(messages)

        # Work on copies
        result = [Message(role=m.role, content=m.content, tool_call_id=m.tool_call_id,
                          tool_calls=m.tool_calls, timestamp=m.timestamp) for m in messages]

        # Identify which messages are protected (system + recent N)
        protected = set()
        protected.add(0)  # system prompt
        for i in range(max(0, len(result) - self._preserve_recent), len(result)):
            protected.add(i)

        # Find trimmable tool outputs, oldest first
        trimmable = [
            (i, m) for i, m in enumerate(result)
            if i not in protected and m.role == "tool" and len(m.content) > MIN_CONTENT_LEN
        ]

        # Also trim old assistant messages with long content
        trimmable += [
            (i, m) for i, m in enumerate(result)
            if i not in protected and m.role == "assistant" and len(m.content) > MIN_CONTENT_LEN
            and (i, m) not in trimmable
        ]

        # Trim oldest first, most aggressively
        for idx, msg in trimmable:
            current_tokens = self._estimate_tokens(result)
            if current_tokens <= self._max_tokens:
                break

            overshoot = current_tokens - self._max_tokens
            chars_to_cut = overshoot * CHARS_PER_TOKEN
            content = result[idx].content

            if chars_to_cut >= len(content) - MIN_CONTENT_LEN:
                # Truncate to minimum
                new_content = content[:MIN_CONTENT_LEN] + TRUNCATION_MARKER
            else:
                keep = max(MIN_CONTENT_LEN, len(content) - chars_to_cut)
                new_content = content[:keep] + TRUNCATION_MARKER

            result[idx] = Message(
                role=msg.role, content=new_content,
                tool_call_id=msg.tool_call_id, tool_calls=msg.tool_calls,
                timestamp=msg.timestamp,
            )

        return result

    @staticmethod
    def _estimate_tokens(messages: list[Message]) -> int:
        """Estimate token count from message content.

        Args:
            messages: Messages to estimate.

        Returns:
            Approximate token count (chars / 4).
        """
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // CHARS_PER_TOKEN
