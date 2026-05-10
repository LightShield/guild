"""Learning loop — post-task knowledge extraction and injection (REQ-09).

Extracts reusable insights from completed tasks and injects confirmed
learnings into future agent prompts.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = [
    "LEARNER_PROMPT",
    "LEARNING_CONTENT_MAX_CHARS",
    "MIN_INJECTION_CONFIDENCE",
    "extract_learnings",
    "format_learnings_for_injection",
    "suggest_prompt_refinements",
]

logger = logging.getLogger(__name__)

LEARNING_CONTENT_MAX_CHARS = 500
MIN_INJECTION_CONFIDENCE = 0.5

LEARNER_PROMPT = (
    "Review the session log below. Extract useful knowledge as JSON lines.\n"
    'Each line: {"category": "pattern|anti_pattern|tool_tip|domain_knowledge",'
    ' "content": "..."}\n'
    "Only extract genuinely reusable insights. Skip trivial observations.\n"
    "Output ONLY valid JSON lines, one per line. No other text."
)

_VALID_CATEGORIES = {"pattern", "anti_pattern", "tool_tip", "domain_knowledge"}

_DEFAULT_CONFIDENCE = 0.3


async def extract_learnings(
    task_id: str,
    storage: Storage,
    provider: LLMProvider,
) -> list[dict]:
    """Run the learner on a completed task's messages.

    Fetches messages for the task's assigned agent, asks the LLM to
    extract learnings, parses JSON lines, and stores valid entries.

    Returns the list of successfully stored learnings.
    """
    task = await storage.get_task(task_id)
    if task is None:
        logger.warning("extract_learnings: task %s not found", task_id)
        return []

    agent_id = task.get("assigned_agent")
    if not agent_id:
        logger.warning("extract_learnings: task %s has no assigned agent", task_id)
        return []

    messages = await storage.get_messages(agent_id)
    if not messages:
        logger.warning("extract_learnings: no messages for agent %s", agent_id)
        return []

    session_log = _format_session_log(messages)

    llm_messages = [
        {"role": "system", "content": LEARNER_PROMPT},
        {"role": "user", "content": session_log},
    ]
    response = await provider.generate(llm_messages)

    raw_lines = (response.content or "").strip().splitlines()
    stored: list[dict] = []

    for line in raw_lines:
        parsed = _parse_learning_line(line)
        if parsed is None:
            continue

        learning_id = await storage.add_learning(
            category=parsed["category"],
            content=parsed["content"],
            confidence=_DEFAULT_CONFIDENCE,
            source_task_id=task_id,
        )
        stored.append(
            {
                "id": learning_id,
                "category": parsed["category"],
                "content": parsed["content"],
                "confidence": _DEFAULT_CONFIDENCE,
            }
        )

    logger.info(
        "Extracted %d learnings from task %s (%d lines skipped)",
        len(stored),
        task_id,
        len(raw_lines) - len(stored),
    )
    return stored


def format_learnings_for_injection(
    learnings: list[dict],
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
        lines.append(f"- [{category}] (confidence: {confidence:.1f}) {content}")

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


def _format_session_log(messages: list[dict]) -> str:
    """Format message history into a readable session log."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate very long messages to keep prompt manageable
        if len(content) > LEARNING_CONTENT_MAX_CHARS:
            content = content[:LEARNING_CONTENT_MAX_CHARS] + "..."
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _parse_learning_line(line: str) -> dict | None:
    """Parse a single JSON line into a learning dict, or None if invalid."""
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Skipping invalid JSON line: %s", line[:80])
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
