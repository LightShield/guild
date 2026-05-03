"""Core data models for Guild.

Pydantic models for agents, tasks, blocks, ports, configuration,
and inter-agent messages.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "AgentState",
    "AgentStatus",
    "BlockDef",
    "BusMessage",
    "GuildConfig",
    "Message",
    "PermissionTier",
    "PortDef",
    "ProviderConfig",
    "Task",
    "TaskStatus",
]


class PermissionTier(str, Enum):
    """Permission levels controlling what agents can do.

    Tiers:
        NOTHING: No tool use at all (safe mode for testing prompts).
        ASK: Agent requests tool use, human approves per-tool.
        SCOPED: All tools allowed within a defined scope (directory/tool set).
        AUTOPILOT: Everything allowed, no approval needed.
    """

    NOTHING = "nothing"
    ASK = "ask"
    SCOPED = "scoped"
    AUTOPILOT = "autopilot"


class AgentStatus(str, Enum):
    """Runtime status of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class PortDef(BaseModel):
    """Definition of a block input/output port.

    Attributes:
        name: Port identifier.
        type_tag: Type tag for compatibility checking (e.g., 'plan', 'code-changes', 'any').
        description: Human-readable description.
        json_schema: Optional JSON schema for port data validation.
    """

    name: str
    type_tag: str = "any"
    description: str = ""
    json_schema: dict[str, Any] | None = None


class Message(BaseModel):
    """A message in the agent conversation or between agents.

    Attributes:
        role: Message role ('system', 'user', 'assistant', 'tool').
        content: Message text content.
        tool_call_id: ID linking a tool result to its call.
        tool_calls: List of tool calls requested by the assistant.
        timestamp: When the message was created.
    """

    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class BusMessage(BaseModel):
    """A message on the internal agent-to-agent bus.

    Attributes:
        source_agent: ID of the sending agent.
        target_agent: ID of the receiving agent.
        port: Named port for the data.
        data: Message payload.
        timestamp: When the message was sent.
    """

    source_agent: str
    target_agent: str
    port: str
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class BlockDef(BaseModel):
    """Definition of an atomic block (agent template).

    Attributes:
        name: Block identifier.
        role: Block's role description.
        system_prompt: System prompt for the agent.
        model: Model override (None = use project default).
        tools: List of tool names this block can use.
        inputs: Typed input port definitions.
        outputs: Typed output port definitions.
        permission: Default permission tier.
        max_retries: Retry count on failure.
    """

    name: str
    role: str
    system_prompt: str = ""
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    inputs: list[PortDef] = Field(default_factory=list)
    outputs: list[PortDef] = Field(default_factory=list)
    permission: PermissionTier = PermissionTier.ASK
    max_retries: int = 1


class AgentState(BaseModel):
    """Runtime state of a running agent.

    Attributes:
        agent_id: Unique agent identifier.
        block_name: Name of the block this agent instantiates.
        status: Current agent status.
        messages: Conversation history.
        task_id: ID of the assigned task.
        created_at: When the agent was created.
        token_usage: Token consumption counters.
    """

    agent_id: str
    block_name: str
    status: AgentStatus = AgentStatus.IDLE
    messages: list[Message] = Field(default_factory=list)
    task_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    token_usage: dict[str, int] = Field(default_factory=lambda: {"input": 0, "output": 0})


class Task(BaseModel):
    """A task assigned to the guild.

    Attributes:
        task_id: Unique task identifier.
        description: Human-readable task description.
        status: Current task status.
        acceptance_criteria: List of criteria for task completion.
        parent_task_id: ID of parent task (for decomposed tasks).
        assigned_agent: ID of the agent working on this task.
        created_at: When the task was created.
        completed_at: When the task was completed.
        result: Task result summary.
    """

    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    acceptance_criteria: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    assigned_agent: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: str | None = None


class ProviderConfig(BaseModel):
    """LLM provider configuration.

    Attributes:
        name: Provider name ('ollama', etc.).
        base_url: Provider API endpoint.
        model: Default model name.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens per response.
    """

    name: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    temperature: float = 0.7
    max_tokens: int = 4096


_DEFAULT_GUILD_MASTER_PROMPT = (
    "You are the Guild Master — the orchestrator for this project. "
    "Your job is to understand the user's request, break it down if needed, "
    "and delegate to the appropriate agents. If the task is simple enough, "
    "handle it directly. Always verify completion against acceptance criteria "
    "before reporting done. Be autonomous — only ask the user when truly stuck."
)

_DEFAULT_GUILD_MASTER_TOOLS = ["file_read", "file_write", "shell", "search", "spawn_agent"]


class GuildConfig(BaseModel):
    """Project-level Guild configuration.

    Attributes:
        version: Config schema version.
        provider: LLM provider settings.
        default_permission: Default permission tier for agents.
        max_concurrent_agents: Max agents running simultaneously.
        max_concurrent_tool_calls: Max parallel tool executions.
        autonomy_timeout_minutes: Max runtime before auto-pause (None = no limit).
        entry_agent: The Guild Master block definition.
    """

    version: str = "0.1.0"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    default_permission: PermissionTier = PermissionTier.ASK
    max_concurrent_agents: int = 1
    max_concurrent_tool_calls: int = 4
    autonomy_timeout_minutes: int | None = None

    entry_agent: BlockDef = Field(default_factory=lambda: BlockDef(
        name="guild-master",
        role="orchestrator",
        system_prompt=_DEFAULT_GUILD_MASTER_PROMPT,
        tools=_DEFAULT_GUILD_MASTER_TOOLS,
        permission=PermissionTier.SCOPED,
    ))
