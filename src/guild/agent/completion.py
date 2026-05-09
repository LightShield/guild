"""Completion heuristics — prevent loops via dedup, nudge, and enriched results."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.tools.base import ToolResult

__all__ = [
    "COMPLETION_NUDGE",
    "DEDUP_MESSAGE",
    "format_tool_result",
    "is_duplicate_call",
    "should_nudge_completion",
]

logger = logging.getLogger(__name__)

COMPLETION_NUDGE: str = (
    "The action above succeeded. If this completes your task, "
    "please summarize what was done and provide your final response. "
    "Do not repeat the same action."
)

DEDUP_MESSAGE: str = (
    "This tool call has already been executed successfully. "
    "Do not repeat it. Move on to the next step or provide your final response."
)

_CLOSURE_HINT: str = "\n\nIf this completes your task, provide your final response."

# Maximum number of successful results to consider "simple"
_SIMPLE_ACTION_THRESHOLD: int = 2


def is_duplicate_call(call: dict, recent_calls: list[dict]) -> bool:
    """Check if a tool call is identical to one already in recent_calls.

    Compares function name and arguments for exact match.
    """
    fn = call.get("function", {})
    call_name = fn.get("name", "")
    call_args = fn.get("arguments", {})

    for prev in recent_calls:
        prev_fn = prev.get("function", {})
        if prev_fn.get("name") == call_name and prev_fn.get("arguments") == call_args:
            return True

    return False


def should_nudge_completion(tool_results: list[ToolResult]) -> bool:
    """Decide whether to inject a completion nudge after tool execution.

    Returns True when all results succeeded and the action count is simple
    (1 or 2 tools). Complex multi-tool sequences should not be nudged.
    """
    if not tool_results:
        return False

    if len(tool_results) >= _SIMPLE_ACTION_THRESHOLD:
        return False

    return all(r.success for r in tool_results)


def format_tool_result(tool_name: str, result: ToolResult) -> str:
    """Format a tool result for inclusion in the message history.

    Success results include a closure hint (Fix A).
    Error results are returned as-is without the hint.
    """
    if result.success:
        return f"[{tool_name}] {result.output}{_CLOSURE_HINT}"

    error_detail = result.error or "Unknown error"
    return f"[{tool_name}] Error: {error_detail}"
