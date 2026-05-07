"""Agent loop — the core while-loop that drives tool-calling agents."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from guild.agent.completion import (
    COMPLETION_NUDGE,
    DEDUP_MESSAGE,
    format_tool_result,
    is_duplicate_call,
    should_nudge_completion,
)
from guild.tools.base import TOOL_SCHEMAS, ToolResult

if TYPE_CHECKING:
    from guild.provider.base import LLMProvider, LLMResponse

__all__ = ["AgentLoop"]

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[dict, str | None], Awaitable[ToolResult]]


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
        working_dir: str | None = None,
        max_turns: int = 50,
    ) -> None:
        self.provider = provider
        self.tool_executors = tool_executors
        self.working_dir = working_dir
        self.max_turns = max_turns
        self.messages: list[dict[str, Any]] = []
        self.recent_tool_calls: list[dict[str, Any]] = []

    async def run(self, system_prompt: str, user_input: str) -> str:
        """Execute the agent loop until completion or max_turns.

        Resets the conversation history. Use send() to continue an
        existing conversation without resetting.

        Returns the final text content from the model.
        """
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        self.recent_tool_calls = []
        return await self._execute_turns()

    async def send(self, user_input: str) -> str:
        """Continue an existing conversation with a new user message.

        Unlike run(), this preserves the full conversation history.
        Raises RuntimeError if run() has not been called first.

        Returns the final text content from the model.
        """
        if not self.messages:
            raise RuntimeError("Must call run() before send().")
        self.messages.append({"role": "user", "content": user_input})
        self.recent_tool_calls = []
        return await self._execute_turns()

    async def _execute_turns(self) -> str:
        """Drive the tool-calling loop until the model stops or max_turns."""
        tool_schemas = self._get_tool_schemas()
        last_content = ""

        for _turn in range(self.max_turns):
            response = await self.provider.generate(self.messages, tools=tool_schemas)
            last_content = response.content or ""

            # Append the assistant message
            assistant_msg = self._build_assistant_message(response)
            self.messages.append(assistant_msg)

            # If no tool calls, we're done
            if not response.has_tool_call:
                break

            # Execute tool calls
            turn_results = await self._execute_tool_calls(response.tool_calls or [])

            # Fix B: Inject completion nudge if appropriate
            if should_nudge_completion(turn_results):
                self.messages.append({"role": "user", "content": COMPLETION_NUDGE})

        return last_content

    async def _execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolResult]:
        """Execute a batch of tool calls, applying dedup guard (Fix C)."""
        results: list[ToolResult] = []

        for call in tool_calls:
            fn_info = call.get("function", {})
            tool_name = fn_info.get("name", "")
            tool_args = fn_info.get("arguments", {})

            # Fix C: Deduplication guard
            if is_duplicate_call(call, self.recent_tool_calls):
                logger.info("Skipping duplicate call: %s", tool_name)
                self.messages.append({"role": "tool", "content": DEDUP_MESSAGE})
                results.append(ToolResult(success=True, output=DEDUP_MESSAGE))
                continue

            # Execute the tool
            result = await self._execute_single_tool(tool_name, tool_args)
            results.append(result)

            # Track for dedup (only track successful calls)
            if result.success:
                self.recent_tool_calls.append(call)

            # Fix A: Format and append result
            formatted = format_tool_result(tool_name, result)
            self.messages.append({"role": "tool", "content": formatted})

        return results

    async def _execute_single_tool(self, tool_name: str, tool_args: dict) -> ToolResult:
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
        except Exception as exc:
            logger.exception("Tool %s raised an exception", tool_name)
            return ToolResult(success=False, output="", error=f"Tool execution failed: {exc}")

    def _build_assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        """Build an assistant message dict from the LLM response."""
        msg: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            msg["tool_calls"] = response.tool_calls
        return msg

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for tools we have executors for."""
        schemas: list[dict[str, Any]] = []
        for name in self.tool_executors:
            if name in TOOL_SCHEMAS:
                schemas.append(TOOL_SCHEMAS[name])
        return schemas
