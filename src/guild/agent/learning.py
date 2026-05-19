"""Learning loop — post-task knowledge extraction and injection (REQ-09).

Extracts reusable insights from completed tasks and injects confirmed
learnings into future agent prompts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

from guild.config.constants import (
    DEFAULT_CONFIDENCE,
    LEARNING_CONTENT_MAX_CHARS,
    LOG_PREVIEW_MAX_CHARS,
    MIN_INJECTION_CONFIDENCE,
)

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

from guild.storage.learnings import LearningRecord

__all__ = [
    "LEARNER_PROMPT",
    "LEARNING_CONTENT_MAX_CHARS",
    "MIN_INJECTION_CONFIDENCE",
    "extract_learnings",
    "format_learnings_for_injection",
    "suggest_prompt_refinements",
]

logger = get_logger(__name__)

LEARNER_PROMPT = (
    "Review the session log below. Extract useful knowledge as JSON lines.\n"
    'Each line: {"category": "pattern|anti_pattern|tool_tip|domain_knowledge",'
    ' "content": "..."}\n'
    "Only extract genuinely reusable insights. Skip trivial observations.\n"
    "Output ONLY valid JSON lines, one per line. No other text."
)

_VALID_CATEGORIES = {"pattern", "anti_pattern", "tool_tip", "domain_knowledge"}


async def extract_learnings(
    task_id: str,
    storage: Storage,
    provider: LLMProvider,
) -> list[dict[str, Any]]:
    """Run the learner on a completed task's messages.

    Fetches messages for the task's assigned agent, asks the LLM to
    extract learnings, parses JSON lines, and stores valid entries.

    Returns the list of successfully stored learnings.
    """
    messages = await _fetch_task_messages(task_id, storage)
    if messages is None:
        return []

    response = await _generate_learnings_response(messages, provider)
    raw_lines = (response.content or "").strip().splitlines()
    stored = await _store_parsed_learnings(raw_lines, task_id, storage)

    logger.info(
        "Extracted %d learnings from task %s (%d lines skipped)",
        len(stored),
        task_id,
        len(raw_lines) - len(stored),
    )
    return stored


async def _fetch_task_messages(task_id: str, storage: Storage) -> list[dict[str, Any]] | None:
    """Fetch messages for a task's assigned agent, or None if unavailable."""
    task = await storage.get_task(task_id)
    if task is None:
        logger.debug("extract_learnings: task %s not found", task_id)
        return None

    agent_id = task.get("assigned_agent")
    if not agent_id:
        logger.debug("extract_learnings: task %s has no assigned agent", task_id)
        return None

    messages = await storage.get_messages(agent_id)
    if not messages:
        logger.debug("extract_learnings: no messages for agent %s", agent_id)
        return None

    return messages


async def _generate_learnings_response(
    messages: list[dict[str, Any]], provider: LLMProvider
) -> Any:
    """Build the learner prompt and generate LLM response."""
    session_log = _format_session_log(messages)
    llm_messages = [
        {"role": "system", "content": LEARNER_PROMPT},
        {"role": "user", "content": session_log},
    ]
    return await provider.generate(llm_messages)


async def _store_parsed_learnings(
    raw_lines: list[str], task_id: str, storage: Storage
) -> list[dict[str, Any]]:
    """Parse raw LLM output lines and store valid learnings."""
    stored: list[dict[str, Any]] = []

    for line in raw_lines:
        parsed = _parse_learning_line(line)
        if parsed is None:
            continue

        learning_id = await storage.add_learning(
            LearningRecord(
                category=parsed["category"],
                content=parsed["content"],
                confidence=DEFAULT_CONFIDENCE,
                source_task_id=task_id,
            )
        )
        stored.append(
            {
                "id": learning_id,
                "category": parsed["category"],
                "content": parsed["content"],
                "confidence": DEFAULT_CONFIDENCE,
            }
        )

    return stored


def format_learnings_for_injection(
    learnings: list[dict[str, Any]],
    max_items: int = 10,
) -> str:
    """Format top learnings as context for injection into agent prompts.

    Filters to learnings with confidence >= 0.5, then takes the top
    max_items sorted by confidence descending.
    """
    eligible = [item for item in learnings if item.get("confidence", 0) >= MIN_INJECTION_CONFIDENCE]

    eligible.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    eligible = eligible[:max_items]

    if not eligible:
        return ""

    lines = ["## Learnings from previous tasks\n"]
    for item in eligible:
        category = item.get("category", "unknown")
        content = item.get("content", "")
        confidence = item.get("confidence", 0)
        lines.append(f"- [hint, confidence: {confidence:.1f}] [{category}] {content}")

    return "\n".join(lines)


async def suggest_prompt_refinements(
    storage: Storage,
    block_name: str | None = None,
) -> list[str]:
    """Analyze learnings and suggest prompt improvements (REQ-09.9).

    Looks for anti_patterns and tool_tips scoped to the given block,
    then generates actionable suggestions for prompt refinement.

    Args:
        storage: Storage instance to query learnings from.
        block_name: Optional block scope to filter learnings.

    Returns:
        List of suggestion strings for prompt improvement.
    """
    learnings = await storage.list_learnings(
        min_confidence=MIN_INJECTION_CONFIDENCE,
        scope=block_name,
    )

    suggestions: list[str] = []

    for learning in learnings:
        category = learning.get("category", "")
        content = learning.get("content", "")

        if category == "anti_pattern":
            suggestions.append(f"Add guard against: {content}")
        elif category == "tool_tip":
            suggestions.append(f"Include tip in prompt: {content}")

    return suggestions


def _format_session_log(messages: list[dict[str, Any]]) -> str:
    """Format message history into a readable session log."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if len(content) > LEARNING_CONTENT_MAX_CHARS:
            content = content[:LEARNING_CONTENT_MAX_CHARS] + "..."
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _parse_learning_line(line: str) -> dict[str, Any] | None:
    """Parse a single JSON line into a learning dict, or None if invalid."""
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Skipping invalid JSON line: %s", line[:LOG_PREVIEW_MAX_CHARS])
        return None

    if not isinstance(data, dict):
        return None

    category = data.get("category", "")
    content = data.get("content", "")

    if category not in _VALID_CATEGORIES:
        logger.debug("Skipping invalid category: %s", category)
        return None

    if not content or not isinstance(content, str):
        return None

    return {"category": category, "content": content}
