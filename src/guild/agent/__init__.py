"""Agent module — core loop, completion heuristics, stuck detection, rollback."""

from guild.agent.completion import (
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.agent.loop import AgentLoop
from guild.agent.rollback import RollbackContext, try_with_rollback
from guild.agent.stuck import StuckDetector

__all__ = [
    "AgentLoop",
    "RollbackContext",
    "StuckDetector",
    "format_tool_result",
    "is_duplicate_call",
    "should_nudge_completion",
    "try_with_rollback",
]
