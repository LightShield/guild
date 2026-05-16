"""Agent spawning — create and track sub-agents as tool calls (REQ-04.3/04.4/04.5)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

from guild.agent.loop import AgentLoop
from guild.config.constants import (
    AGENT_ID_PREFIX_LEN,
    MAX_SPAWN_DEPTH,
    SUB_AGENT_MAX_TURNS,
    TASK_LOG_PREVIEW_CHARS,
)
from guild.tools.base import ToolResult

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.orchestration.bus import MessageBus
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = ["AgentSpawner", "SUB_AGENT_MAX_TURNS"]

logger = get_logger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful sub-agent. Complete the assigned task thoroughly "
    "and return a clear summary of your results."
)


class AgentSpawner:
    """Manages spawning and tracking of sub-agents.

    Sub-agents are AgentLoop instances that run to completion and
    return their result. Spawning is exposed as a tool call so any
    agent (including orchestrators) can create workers.
    """

    def __init__(
        self,
        provider: LLMProvider,
        storage: Storage | None,
        bus: MessageBus,
        working_dir: str | None = None,
        max_depth: int = MAX_SPAWN_DEPTH,
    ) -> None:
        self._provider = provider
        self._storage = storage
        self._bus = bus
        self._working_dir = working_dir
        self._max_depth = max_depth
        self._current_depth = 0
        self._agents: dict[str, AgentLoop] = {}

    async def spawn(
        self,
        task: str,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        agent_id: str | None = None,
    ) -> str:
        """Spawn a new sub-agent and run it to completion.

        Args:
            task: Task description for the sub-agent.
            system_prompt: Optional system prompt override.
            tools: Optional list of tool names to restrict available tools.
            agent_id: Optional explicit agent ID (auto-generated if None).

        Returns:
            The final text result from the sub-agent.

        Raises:
            RuntimeError: If spawn depth exceeds the configured max_depth.
        """
        if self._current_depth >= self._max_depth:
            msg = (
                f"Spawn depth {self._current_depth} exceeds max_depth "
                f"{self._max_depth}"
            )
            raise RuntimeError(msg)

        agent_id = agent_id or f"agent-{uuid.uuid4().hex[:AGENT_ID_PREFIX_LEN]}"
        prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

        # Build tool executors (empty for now — sub-agents inherit none
        # unless explicitly provided via the tools parameter)
        tool_executors: dict[str, Any] = {}

        loop = AgentLoop(
            provider=self._provider,
            tool_executors=tool_executors,
            working_dir=self._working_dir,
            max_turns=SUB_AGENT_MAX_TURNS,
        )
        self._agents[agent_id] = loop

        logger.info("Spawning sub-agent %s: %s", agent_id, task[:TASK_LOG_PREVIEW_CHARS])
        result = await loop.run(prompt, task)

        return result

    def get_agent(self, agent_id: str) -> AgentLoop | None:
        """Get a tracked agent by ID, or None if not found."""
        return self._agents.get(agent_id)

    @property
    def active_agents(self) -> list[str]:
        """List IDs of all tracked agents."""
        return list(self._agents.keys())

    async def execute_spawn(
        self, args: dict[str, Any], working_dir: str | None = None
    ) -> ToolResult:
        """Execute a spawn request from the spawn_agent tool.

        Called by AgentLoop when the model invokes the spawn_agent tool.
        """
        task = args.get("task", "")
        if not task:
            return ToolResult(success=False, output="", error="Missing required 'task' parameter")

        system_prompt = args.get("system_prompt")
        result = await self.spawn(task=task, system_prompt=system_prompt)
        return ToolResult(success=True, output=result)
