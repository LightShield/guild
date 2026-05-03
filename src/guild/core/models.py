"""Core data models for Guild."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class PermissionTier(str, Enum):
    NOTHING = "nothing"
    ASK = "ask"
    SCOPED = "scoped"
    AUTOPILOT = "autopilot"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"  # waiting for human / another agent
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


# --- Port types ---


class PortDef(BaseModel):
    """Definition of a block input/output port."""

    name: str
    type_tag: str = "any"  # plan, code-changes, review, test-results, text, files, any
    description: str = ""
    json_schema: dict[str, Any] | None = None  # optional JSON schema for port data


# --- Messages ---


class Message(BaseModel):
    """A message in the agent conversation or between agents."""

    role: str  # system, user, assistant, tool
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class BusMessage(BaseModel):
    """A message on the internal agent-to-agent bus."""

    source_agent: str
    target_agent: str
    port: str
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


# --- Agent & Block ---


class BlockDef(BaseModel):
    """Definition of an atomic block (agent template)."""

    name: str
    role: str
    system_prompt: str = ""
    model: str | None = None  # None = use project default
    tools: list[str] = Field(default_factory=list)
    inputs: list[PortDef] = Field(default_factory=list)
    outputs: list[PortDef] = Field(default_factory=list)
    permission: PermissionTier = PermissionTier.ASK
    max_retries: int = 1


class AgentState(BaseModel):
    """Runtime state of a running agent."""

    agent_id: str
    block_name: str
    status: AgentStatus = AgentStatus.IDLE
    messages: list[Message] = Field(default_factory=list)
    task_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    token_usage: dict[str, int] = Field(default_factory=lambda: {"input": 0, "output": 0})


# --- Task ---


class Task(BaseModel):
    """A task assigned to the guild."""

    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    acceptance_criteria: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    assigned_agent: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: str | None = None


# --- Config ---


class ProviderConfig(BaseModel):
    """LLM provider configuration."""

    name: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    temperature: float = 0.7
    max_tokens: int = 4096


class GuildConfig(BaseModel):
    """Project-level Guild configuration."""

    version: str = "0.1.0"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    default_permission: PermissionTier = PermissionTier.ASK
    max_concurrent_agents: int = 1
    max_concurrent_tool_calls: int = 4
    autonomy_timeout_minutes: int | None = None  # None = no timeout

    entry_agent: BlockDef = Field(default_factory=lambda: BlockDef(
        name="guild-master",
        role="orchestrator",
        system_prompt=(
            "You are the Guild Master — the orchestrator for this project. "
            "Your job is to understand the user's request, break it down if needed, "
            "and delegate to the appropriate agents. If the task is simple enough, "
            "handle it directly. Always verify completion against acceptance criteria "
            "before reporting done. Be autonomous — only ask the user when truly stuck."
        ),
        tools=["file_read", "file_write", "shell", "search", "spawn_agent"],
        permission=PermissionTier.SCOPED,
    ))
