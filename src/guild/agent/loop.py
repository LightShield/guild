"""Agent loop — the core while-loop that drives tool-calling agents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

from guild.agent.completion import (
    COMPLETION_NUDGE,
    DEDUP_MESSAGE,
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.agent.message import Message
from guild.config.constants import DEFAULT_MAX_TURNS, LOOP_CONTENT_PREVIEW_CHARS
from guild.tools.base import TOOL_SCHEMAS, ToolResult

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.agent.stuck import StuckDetector
    from guild.provider.base import LLMProvider, LLMResponse

__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "DEFAULT_MAX_TURNS",
    "ESCALATION_TEMPLATE",
    "SELF_REVIEW_PROMPT",
    "STUCK_RECOVERY_PROMPT",
    "ToolExecutor",
]

logger = get_logger(__name__)

STUCK_RECOVERY_PROMPT = (
    "You appear to be stuck (repeating the same action or encountering repeated errors). "
    "Try a completely different approach to accomplish the task. "
    "If you cannot find an alternative, explain what you're stuck on."
)

_TEST_FAILURE_RECOVERY_PROMPT = (
    "A test or command keeps failing with the same error. "
    "Do NOT re-run the same command. Instead:\n"
    "1. Read the error message carefully\n"
    "2. Identify the root cause (typo? wrong assertion? missing import?)\n"
    "3. Fix the SOURCE CODE that's causing the failure\n"
    "4. Then re-run to verify"
)

SELF_REVIEW_PROMPT = (
    "Review what you just did. Look for bugs, edge cases, security issues, "
    "and spec violations. If you find problems, fix them now. "
    "If everything looks correct, confirm with a brief summary."
)

ESCALATION_TEMPLATE = (
    "I'm stuck and need help.\n\n"
    "Task: {task}\n"
    "What I tried: {attempts}\n"
    "Where I'm stuck: {reason}\n"
    "What I need: {need}"
)

ToolExecutor = Callable[[dict[str, Any], str | None], Awaitable[ToolResult]]


@dataclass
class AgentLoopConfig:
    """Configuration for the agent loop."""

    working_dir: str | None = None
    max_turns: int = DEFAULT_MAX_TURNS
    stuck_detector: StuckDetector | None = field(default=None)
    token_budget: int = 0


class AgentLoop:
    """Core agent loop: call model, execute tools, repeat until done.

    Integrates three completion heuristics to prevent looping:
    - Fix A: Enriched tool results with closure hint
    - Fix B: Completion nudge after simple successful actions
    - Fix C: Deduplication guard for identical tool calls
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_executors: dict[str, ToolExecutor],
        config: AgentLoopConfig | None = None,
        *,
        working_dir: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        stuck_detector: StuckDetector | None = None,
        token_budget: int = 0,
    ) -> None:
        if config is not None:
            working_dir = config.working_dir
            max_turns = config.max_turns
            stuck_detector = config.stuck_detector
            token_budget = config.token_budget
        self.provider = provider
        self.tool_executors = tool_executors
        self.working_dir = working_dir
        self.max_turns = max_turns
        self.stuck_detector = stuck_detector
        self.token_budget = token_budget
        self.messages: list[Message] = []
        self.recent_tool_calls: list[dict[str, Any]] = []
        self._task_description: str = ""
        self._attempted_tools: list[str] = []
        self._recovery_attempted: bool = False

        # Token usage tracking (REQ-10.1)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_tool_calls: int = 0

    async def run(self, system_prompt: str, user_input: str, self_review: bool = False) -> str:
        """Execute the agent loop until completion or max_turns.

        Resets the conversation history. Use send() to continue an
        existing conversation without resetting.

        Args:
            system_prompt: System prompt for the model.
            user_input: The user's task description.
            self_review: If True, inject adversarial self-review after success.

        Returns the final text content from the model.
        """
        self.messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_input),
        ]
        self.recent_tool_calls = []
        self._task_description = user_input
        self._attempted_tools = []
        self._recovery_attempted = False
        if self.stuck_detector:
            self.stuck_detector.reset()

        result = await self._execute_turns()

        if self_review and not result.startswith("I'm stuck and need help."):
            result = await self._run_self_review()

        return result

    async def send(self, user_input: str) -> str:
        """Continue an existing conversation with a new user message.

        Unlike run(), this preserves the full conversation history.
        Raises RuntimeError if run() has not been called first.

        Returns the final text content from the model.
        """
        if not self.messages:
            raise RuntimeError("Must call run() before send().")
        self.messages.append(Message(role="user", content=user_input))
        self.recent_tool_calls = []
        return await self._execute_turns()

    async def _execute_turns(self) -> str:
        """Drive the tool-calling loop until the model stops or max_turns."""
        tool_schemas = self._get_tool_schemas()
        last_content = ""

        for _turn in range(self.max_turns):
            # Budget check (REQ-10.2): stop if token budget exceeded
            if self._budget_exceeded():
                total = self.total_input_tokens + self.total_output_tokens
                logger.warning(
                    "Token budget exceeded, stopping loop (used=%d, budget=%d)",
                    total,
                    self.token_budget,
                )
                break

            raw_messages = [m.to_dict() for m in self.messages]
            response = await self.provider.generate(raw_messages, tools=tool_schemas)
            last_content = response.content or ""

            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            assistant_msg = self._build_assistant_message(response)
            self.messages.append(assistant_msg)

            if not response.has_tool_call:
                break

            tool_calls = response.tool_calls or []
            self._track_tool_calls(tool_calls)
            self.total_tool_calls += len(tool_calls)

            turn_results = await self._execute_tool_calls(tool_calls)

            escalation = self._check_stuck(turn_results)
            if escalation is not None:
                return escalation

            if should_nudge_completion(turn_results):
                self.messages.append(Message(role="user", content=COMPLETION_NUDGE))

        return last_content

    def _budget_exceeded(self) -> bool:
        """Return True if the token budget has been exceeded."""
        if not self.token_budget:
            return False
        total = self.total_input_tokens + self.total_output_tokens
        return total > self.token_budget

    def _track_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        """Record tool calls for stuck detection and escalation context."""
        for call in tool_calls:
            fn_info = call.get("function", {})
            tool_name = fn_info.get("name", "")
            if tool_name and tool_name not in self._attempted_tools:
                self._attempted_tools.append(tool_name)
            if self.stuck_detector:
                self.stuck_detector.record_tool_call(call)

    def _check_stuck(self, turn_results: list[ToolResult]) -> str | None:
        """Check if stuck; attempt recovery or escalate. Returns escalation or None."""
        if not self.stuck_detector:
            return None

        any_failure = any(not r.success for r in turn_results)
        error_msg = next((r.error for r in turn_results if not r.success and r.error), None)
        self.stuck_detector.record_turn(success=not any_failure, error=error_msg)

        if not self.stuck_detector.is_stuck():
            return None

        if not self._recovery_attempted:
            return self._attempt_recovery()
        return self._produce_escalation()

    def _attempt_recovery(self) -> str | None:
        """Inject recovery prompt and reset detector. Returns None (continue loop)."""
        self._recovery_attempted = True
        reason = self.stuck_detector.get_reason() if self.stuck_detector else ""
        logger.warning("Stuck detected (%s), attempting recovery", reason)
        prompt = self._select_recovery_prompt(reason)
        if self.stuck_detector:
            self.stuck_detector.reset()
        self.messages.append(Message(role="user", content=prompt))
        return None  # Continue the loop

    def _select_recovery_prompt(self, reason: str) -> str:
        """Choose recovery prompt based on the type of stuck condition."""
        reason_lower = reason.lower()
        if any(kw in reason_lower for kw in ("exit", "code 1", "failed", "error", "assert")):
            return _TEST_FAILURE_RECOVERY_PROMPT
        return STUCK_RECOVERY_PROMPT

    def _produce_escalation(self) -> str:
        """Build and return a structured escalation message."""
        reason = self.stuck_detector.get_reason() if self.stuck_detector else "Unknown"
        attempts = ", ".join(self._attempted_tools) if self._attempted_tools else "None"
        escalation = ESCALATION_TEMPLATE.format(
            task=self._task_description,
            attempts=attempts,
            reason=reason,
            need="Human guidance to resolve the blocking issue",
        )
        self.messages.append(Message(role="assistant", content=escalation))
        return escalation

    async def _run_self_review(self) -> str:
        """Inject self-review prompt and execute one more round."""
        self.messages.append(Message(role="user", content=SELF_REVIEW_PROMPT))
        self.recent_tool_calls = []
        return await self._execute_turns()

    async def _execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolResult]:
        """Execute a batch of tool calls, applying dedup guard (Fix C)."""
        results: list[ToolResult] = []

        for call in tool_calls:
            fn_info = call.get("function", {})
            tool_name = fn_info.get("name", "")
            tool_args = fn_info.get("arguments", {})

            if is_duplicate_call(call, self.recent_tool_calls):
                logger.debug("Skipping duplicate call: %s", tool_name)
                self.messages.append(Message(role="tool", content=DEDUP_MESSAGE))
                results.append(ToolResult(success=True, output=DEDUP_MESSAGE))
                continue

            result = await self._execute_single_tool(tool_name, tool_args)
            results.append(result)

            if result.success:
                self.recent_tool_calls.append(call)

            formatted = format_tool_result(tool_name, result)
            self.messages.append(Message(role="tool", content=formatted))

        return results

    async def _execute_single_tool(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        """Execute a single tool by name, handling unknown tools gracefully."""
        executor = self.tool_executors.get(tool_name)
        if executor is None:
            logger.warning("Unknown tool requested: %s", tool_name)
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Unknown tool: {tool_name}. " f"Available: {list(self.tool_executors.keys())}"
                ),
            )

        try:
            return await executor(tool_args, self.working_dir)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("Tool %s raised an exception", tool_name, exc_info=True)
            return ToolResult(success=False, output="", error=f"Tool execution failed: {exc}")

    def _build_assistant_message(self, response: LLMResponse) -> Message:
        """Build an assistant Message from the LLM response."""
        return Message(
            role="assistant",
            content=response.content or "",
            tool_calls=response.tool_calls if response.tool_calls else None,
        )

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for tools we have executors for, in Ollama format."""
        schemas: list[dict[str, Any]] = []
        for name in self.tool_executors:
            if name in TOOL_SCHEMAS:
                schemas.append({"type": "function", "function": TOOL_SCHEMAS[name]})
        return schemas

    def generate_timeout_report(self) -> str:
        """Generate a progress report summarizing accomplishments before timeout.

        Returns a structured summary including:
        - Tools used and their outcomes
        - Number of turns completed
        - Last assistant message content
        """
        tools_used = list(dict.fromkeys(self._attempted_tools))  # preserve order, dedup
        turns_completed = len([m for m in self.messages if m.role == "assistant"])
        last_assistant = ""
        for msg in reversed(self.messages):
            if msg.role == "assistant" and msg.content:
                last_assistant = msg.content[:LOOP_CONTENT_PREVIEW_CHARS]
                break

        parts: list[str] = [
            f"Timeout reached after {turns_completed} turn(s).",
            f"Tools used: {', '.join(tools_used) if tools_used else 'none'}.",
            f"Total tool calls: {self.total_tool_calls}.",
        ]
        if last_assistant:
            parts.append(f"Last progress: {last_assistant}")

        return " ".join(parts)
