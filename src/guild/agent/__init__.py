"""Agent module — core loop, completion heuristics, and stuck detection."""

from guild.agent.completion import (
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.agent.loop import AgentLoop
from guild.agent.stuck import StuckDetector

__all__ = [
    "AgentLoop",
    "StuckDetector",
    "format_tool_result",
    "is_duplicate_call",
    "should_nudge_completion",
]
