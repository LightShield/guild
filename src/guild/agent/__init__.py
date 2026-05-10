"""Agent module — core loop, completion heuristics, stuck detection, rollback, learning."""

from guild.agent.budget import BUDGET_ALERT_THRESHOLDS, check_budget_alert
from guild.agent.checkpoint import (
    Checkpoint,
    load_checkpoint,
    recover_from_checkpoint,
    save_checkpoint,
)
from guild.agent.completion import (
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.agent.context import ContextManager
from guild.agent.cost import COST_TABLE, estimate_cost, format_cost_summary
from guild.agent.learning import extract_learnings, format_learnings_for_injection
from guild.agent.loop import DEFAULT_MAX_TURNS, AgentLoop
from guild.agent.message import Message
from guild.agent.prompts import GUILD_MASTER_PROMPT
from guild.agent.ratelimit import RateLimiter, ToolQueue
from guild.agent.rollback import RollbackContext, try_with_rollback
from guild.agent.stuck import StuckDetector

__all__ = [
    "AgentLoop",
    "BUDGET_ALERT_THRESHOLDS",
    "DEFAULT_MAX_TURNS",
    "GUILD_MASTER_PROMPT",
    "Message",
    "COST_TABLE",
    "Checkpoint",
    "ContextManager",
    "RateLimiter",
    "RollbackContext",
    "StuckDetector",
    "ToolQueue",
    "check_budget_alert",
    "estimate_cost",
    "extract_learnings",
    "format_cost_summary",
    "format_learnings_for_injection",
    "format_tool_result",
    "is_duplicate_call",
    "load_checkpoint",
    "recover_from_checkpoint",
    "save_checkpoint",
    "should_nudge_completion",
    "try_with_rollback",
]
