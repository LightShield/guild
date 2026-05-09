"""Agent spawning — create and track sub-agents as tool calls (REQ-04.3/04.4/04.5)."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from guild.agent.loop import AgentLoop
from guild.tools.base import ToolResult

if TYPE_CHECKING:
    from guild.orchestration.bus import MessageBus
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = ["AgentSpawner"]

logger = logging.getLogger(__name__)

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
    ) -> None:
        self._provider = provider
        self._storage = storage
        self._bus = bus
        self._working_dir = working_dir
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
        """
        agent_id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

        # Build tool executors (empty for now — sub-agents inherit none
        # unless explicitly provided via the tools parameter)
        tool_executors: dict = {}

        loop = AgentLoop(
            provider=self._provider,
            tool_executors=tool_executors,
            working_dir=self._working_dir,
            max_turns=30,
        )
        self._agents[agent_id] = loop

        logger.info("Spawning sub-agent %s: %s", agent_id, task[:80])
        result = await loop.run(prompt, task)

        return result

    def get_agent(self, agent_id: str) -> AgentLoop | None:
        """Get a tracked agent by ID, or None if not found."""
        return self._agents.get(agent_id)

    @property
    def active_agents(self) -> list[str]:
        """List IDs of all tracked agents."""
        return list(self._agents.keys())

    async def execute_spawn(self, args: dict, working_dir: str | None = None) -> ToolResult:
        """Execute a spawn request from the spawn_agent tool.

        Called by AgentLoop when the model invokes the spawn_agent tool.
        """
        task = args.get("task", "")
        if not task:
            return ToolResult(success=False, output="", error="Missing required 'task' parameter")

        system_prompt = args.get("system_prompt")
        result = await self.spawn(task=task, system_prompt=system_prompt)
        return ToolResult(success=True, output=result)
