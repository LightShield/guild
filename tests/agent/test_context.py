"""Tests for agent/context.py — multi-tier context compression (REQ-07.4, 07.8, 07.10)."""

from __future__ import annotations

import copy

import pytest

from guild.agent.context import (
    CHARS_PER_TOKEN,
    MIN_CONTENT_LEN,
    TRUNCATION_MARKER,
    ContextManager,
)
from guild.agent.message import Message


def _make_messages(
    tool_content_len: int = 200,
    count: int = 10,
) -> list[Message]:
    """Build a message list with system + alternating assistant/tool messages."""
    msgs: list[Message] = [Message(role="system", content="You are a helpful agent.")]
    for i in range(count):
        msgs.append(Message(role="assistant", content=f"Calling tool {i}"))
        msgs.append(Message(role="tool", content="x" * tool_content_len))
    return msgs


@pytest.mark.unit
class TestEstimateTokens:
    """Token estimation from content length."""

    def test_estimate_tokens_from_content_length(self) -> None:
        """Token count equals total chars / CHARS_PER_TOKEN."""
        cm = ContextManager()
        messages = [
            Message(role="system", content="a" * 100),
            Message(role="user", content="b" * 200),
        ]
        expected = (100 + 200) // CHARS_PER_TOKEN
        assert cm.estimate_tokens(messages) == expected

    def test_estimate_tokens_empty_messages(self) -> None:
        """Empty list returns zero tokens."""
        cm = ContextManager()
        assert cm.estimate_tokens([]) == 0


@pytest.mark.unit
class TestNeedsCompaction:
    """Compaction threshold detection."""

    def test_needs_compaction_false_when_under_threshold(self) -> None:
        """Returns False when token count is below 70% of max."""
        cm = ContextManager(max_tokens=1000, compact_threshold=0.7)
        # 100 chars = 25 tokens, well under 700 threshold
        messages = [Message(role="user", content="a" * 100)]
        assert cm.needs_compaction(messages) is False

    def test_needs_compaction_true_when_over_threshold(self) -> None:
        """Returns True when token count meets or exceeds threshold."""
        cm = ContextManager(max_tokens=100, compact_threshold=0.7)
        # 280 chars = 70 tokens, at the 70% threshold of 100
        messages = [Message(role="user", content="a" * 280)]
        assert cm.needs_compaction(messages) is True


@pytest.mark.unit
class TestCompact:
    """Tier 1 MicroCompact: truncate old tool outputs."""

    def test_compact_truncates_old_tool_outputs(self) -> None:
        """Old tool messages get truncated when over threshold."""
        cm = ContextManager(max_tokens=200, preserve_recent=2, compact_threshold=0.7)
        messages = _make_messages(tool_content_len=300, count=5)

        result = cm.compact(messages)

        # Find old (non-protected) tool messages — they should be truncated
        protected_start = len(result) - 2
        for i, msg in enumerate(result):
            if msg.role == "tool" and i < protected_start:
                assert len(msg.content) <= MIN_CONTENT_LEN + len(TRUNCATION_MARKER)

    def test_compact_preserves_system_prompt(self) -> None:
        """System prompt (first message) is never truncated."""
        long_system = "You are a helpful agent. " * 100
        cm = ContextManager(max_tokens=50, preserve_recent=2, compact_threshold=0.7)
        messages = [
            Message(role="system", content=long_system),
            Message(role="assistant", content="ok"),
            Message(role="tool", content="x" * 500),
            Message(role="assistant", content="done"),
        ]
        result = cm.compact(messages)
        assert result[0].content == long_system

    def test_compact_preserves_recent_messages(self) -> None:
        """Recent N messages are preserved unchanged."""
        cm = ContextManager(max_tokens=100, preserve_recent=4, compact_threshold=0.7)
        messages = _make_messages(tool_content_len=300, count=6)
        original_recent = [copy.copy(m) for m in messages[-4:]]

        result = cm.compact(messages)

        for orig, compacted in zip(original_recent, result[-4:], strict=True):
            assert compacted.content == orig.content
            assert compacted.role == orig.role

    def test_compact_does_not_remove_messages(self) -> None:
        """Compaction never removes messages from the list."""
        cm = ContextManager(max_tokens=50, preserve_recent=2, compact_threshold=0.7)
        messages = _make_messages(tool_content_len=500, count=8)
        original_count = len(messages)

        result = cm.compact(messages)

        assert len(result) == original_count

    def test_compact_does_not_mutate_input(self) -> None:
        """Compaction creates a deep copy, leaving input unchanged."""
        cm = ContextManager(max_tokens=50, preserve_recent=2, compact_threshold=0.7)
        messages = _make_messages(tool_content_len=500, count=4)
        original_content = messages[2].content

        cm.compact(messages)

        assert messages[2].content == original_content


@pytest.mark.unit
class TestHandoffArtifact:
    """Structured handoff for context resets."""

    def test_handoff_artifact_includes_task(self) -> None:
        """Handoff artifact contains the original task description."""
        cm = ContextManager()
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="do stuff"),
        ]
        artifact = cm.create_handoff_artifact(messages, "Implement feature X")
        assert "Implement feature X" in artifact

    def test_handoff_artifact_includes_decisions(self) -> None:
        """Handoff artifact includes decisions from assistant messages."""
        cm = ContextManager()
        messages = [
            Message(role="system", content="sys"),
            Message(role="assistant", content="Decision: use async approach"),
            Message(role="tool", content="file written"),
        ]
        artifact = cm.create_handoff_artifact(messages, "Build API")
        assert "Decision: use async approach" in artifact

    def test_handoff_artifact_includes_completed_actions(self) -> None:
        """Handoff artifact includes completed tool actions."""
        cm = ContextManager()
        messages = [
            Message(role="system", content="sys"),
            Message(role="tool", content="Created file src/main.py"),
            Message(role="tool", content="Wrote 150 chars to config.yaml"),
        ]
        artifact = cm.create_handoff_artifact(messages, "Setup project")
        assert "Created file src/main.py" in artifact
        assert "Wrote 150 chars to config.yaml" in artifact

    def test_handoff_artifact_structure(self) -> None:
        """Handoff artifact has expected markdown sections."""
        cm = ContextManager()
        artifact = cm.create_handoff_artifact([], "My task")
        assert "## Context Handoff" in artifact
        assert "### Task" in artifact
        assert "### Key Decisions" in artifact
        assert "### Completed Actions" in artifact
        assert "### Remaining Work" in artifact


@pytest.mark.unit
class TestSeparateStaticDynamic:
    """Static/dynamic prompt separation for cache efficiency."""

    def test_separate_static_dynamic_splits_correctly(self) -> None:
        """Static part is system prompt; dynamic includes learnings + task."""
        static, dynamic = ContextManager.separate_static_dynamic(
            system_prompt="You are an agent.",
            learnings="Prefer async IO.",
            task="Fix the bug in parser.py",
        )
        assert static == "You are an agent."
        assert "Prefer async IO." in dynamic
        assert "Fix the bug in parser.py" in dynamic

    def test_static_part_is_stable_across_calls(self) -> None:
        """Static part does not change when learnings/task change."""
        system = "You are an agent with tools."
        static1, _ = ContextManager.separate_static_dynamic(
            system_prompt=system,
            learnings="Learning A",
            task="Task 1",
        )
        static2, _ = ContextManager.separate_static_dynamic(
            system_prompt=system,
            learnings="Learning B",
            task="Task 2",
        )
        assert static1 == static2 == system

    def test_dynamic_part_empty_when_no_learnings_or_task(self) -> None:
        """Dynamic part is empty string when both inputs are empty."""
        _, dynamic = ContextManager.separate_static_dynamic(
            system_prompt="sys",
            learnings="",
            task="",
        )
        assert dynamic == ""


# ======================================================================
# Context manager empty content branch (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestContextManagerEmptyContentBranch:
    """Cover context manager branches with empty content."""

    def test_estimate_tokens_with_empty_content(self) -> None:
        """Messages with empty/None content don\'t add to token count."""
        cm = ContextManager()
        messages = [
            Message(role="system", content=""),
            Message(role="user", content=""),
            Message(role="tool", content=""),
        ]
        # All empty content -- should be 0 tokens
        assert cm.estimate_tokens(messages) == 0

    def test_compact_empty_messages_returns_empty(self) -> None:
        """compact() returns [] for empty messages list (line 60)."""
        cm = ContextManager()
        result = cm.compact([])
        assert result == []

    def test_compact_already_within_threshold(self) -> None:
        """compact() exits early when tokens are already within threshold (75 branch)."""
        cm = ContextManager(max_tokens=10000, preserve_recent=2)
        messages = [
            Message(role="system", content="Hello"),
            Message(role="tool", content="short"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="bye"),
        ]
        # These are very short -- within threshold, so no truncation needed
        result = cm.compact(messages)
        # Content should be unchanged
        assert result[1].content == "short"

    def test_protected_indices_no_system_prompt(self) -> None:
        """When first message is not system, index 0 is not protected (151->154)."""
        cm = ContextManager(preserve_recent=2)
        messages = [
            Message(role="user", content="first"),
            Message(role="assistant", content="second"),
            Message(role="tool", content="third"),
            Message(role="user", content="fourth"),
        ]
        protected = cm._protected_indices(messages)
        # Index 0 is NOT protected since role != "system"
        assert 0 not in protected
        # Recent 2 are protected
        assert 2 in protected
        assert 3 in protected

    def test_truncate_message_short_content_unchanged(self) -> None:
        """_truncate_message doesn\'t truncate short content (line 164)."""
        cm = ContextManager()
        msg = Message(role="tool", content="short")
        assert len("short") <= MIN_CONTENT_LEN
        cm._truncate_message(msg)
        assert msg.content == "short"

    def test_extract_decisions_finds_decision_prefix(self) -> None:
        """_extract_decisions finds lines starting with \'Decision:\' (line 177->175)."""
        cm = ContextManager()
        messages = [
            Message(role="assistant", content="Decision: use SQLite\nOther line"),
            Message(role="user", content="ok"),
        ]
        decisions = cm._extract_decisions(messages)
        assert len(decisions) == 1
        assert "Decision: use SQLite" in decisions[0]

    def test_extract_completed_actions_empty_first_line(self) -> None:
        """_extract_completed_actions skips empty first lines (190->184)."""
        cm = ContextManager()
        messages = [
            Message(role="tool", content="\nsecond line here"),
            Message(role="tool", content=""),
        ]
        actions = cm._extract_completed_actions(messages)
        # First message: first_line is "" (empty after split/strip) -- skipped
        # Second message: content is "" -- first_line is "" -- skipped
        assert actions == []
