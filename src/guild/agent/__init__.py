"""Agent module — core loop, completion heuristics, stuck detection, rollback, learning."""

from guild.agent.checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from guild.agent.completion import (
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.agent.context import ContextManager
from guild.agent.learning import extract_learnings, format_learnings_for_injection
from guild.agent.loop import AgentLoop
from guild.agent.ratelimit import RateLimiter, ToolQueue
from guild.agent.rollback import RollbackContext, try_with_rollback
from guild.agent.stuck import StuckDetector

__all__ = [
    "AgentLoop",
    "Checkpoint",
    "ContextManager",
    "RateLimiter",
    "RollbackContext",
    "StuckDetector",
    "ToolQueue",
    "extract_learnings",
    "format_learnings_for_injection",
    "format_tool_result",
    "is_duplicate_call",
    "load_checkpoint",
    "save_checkpoint",
    "should_nudge_completion",
    "try_with_rollback",
]
