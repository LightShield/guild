"""Tests for core/models.py — data model validation, enums, defaults."""

import pytest

pytestmark = pytest.mark.unit
from datetime import datetime

from guild.core.models import (
    AgentState, AgentStatus, BlockDef, BusMessage, GuildConfig,
    Message, PermissionTier, PortDef, ProviderConfig, Task, TaskStatus,
)


# --- Enums ---

class TestPermissionTier:
    def test_all_tiers_exist(self):
        assert set(PermissionTier) == {
            PermissionTier.NOTHING, PermissionTier.ASK,
            PermissionTier.SCOPED, PermissionTier.AUTOPILOT,
        }

    def test_tier_values(self):
        assert PermissionTier.NOTHING.value == "nothing"
        assert PermissionTier.ASK.value == "ask"
        assert PermissionTier.SCOPED.value == "scoped"
        assert PermissionTier.AUTOPILOT.value == "autopilot"

    def test_tier_from_string(self):
        assert PermissionTier("ask") == PermissionTier.ASK


class TestAgentStatus:
    def test_all_statuses(self):
        expected = {"idle", "running", "waiting", "paused", "done", "failed"}
        assert {s.value for s in AgentStatus} == expected


class TestTaskStatus:
    def test_all_statuses(self):
        expected = {"pending", "in_progress", "verifying", "done", "failed", "blocked"}
        assert {s.value for s in TaskStatus} == expected


# --- PortDef ---

class TestPortDef:
    def test_defaults(self):
        p = PortDef(name="test")
        assert p.type_tag == "any"
        assert p.description == ""
        assert p.json_schema is None

    def test_with_type(self):
        p = PortDef(name="code", type_tag="code-changes", description="Code output")
        assert p.type_tag == "code-changes"


# --- Message ---

class TestMessage:
    def test_basic_message(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"
        assert m.tool_call_id is None
        assert m.tool_calls is None
        assert isinstance(m.timestamp, datetime)

    def test_tool_message(self):
        m = Message(role="tool", content="result", tool_call_id="call_0")
        assert m.tool_call_id == "call_0"


# --- BusMessage ---

class TestBusMessage:
    def test_bus_message(self):
        m = BusMessage(source_agent="a1", target_agent="a2", port="output", data={"key": "val"})
        assert m.source_agent == "a1"
        assert m.data == {"key": "val"}


# --- BlockDef ---

class TestBlockDef:
    def test_defaults(self):
        b = BlockDef(name="test", role="worker")
        assert b.system_prompt == ""
        assert b.model is None
        assert b.tools == []
        assert b.inputs == []
        assert b.outputs == []
        assert b.permission == PermissionTier.ASK
        assert b.max_retries == 1

    def test_with_ports(self):
        b = BlockDef(
            name="coder", role="coder",
            inputs=[PortDef(name="spec", type_tag="plan")],
            outputs=[PortDef(name="changes", type_tag="code-changes")],
        )
        assert len(b.inputs) == 1
        assert b.inputs[0].type_tag == "plan"


# --- AgentState ---

class TestAgentState:
    def test_defaults(self):
        a = AgentState(agent_id="a1", block_name="coder")
        assert a.status == AgentStatus.IDLE
        assert a.messages == []
        assert a.token_usage == {"input": 0, "output": 0}


# --- Task ---

class TestTask:
    def test_defaults(self):
        t = Task(task_id="t1", description="fix bug")
        assert t.status == TaskStatus.PENDING
        assert t.acceptance_criteria == []
        assert t.parent_task_id is None
        assert t.completed_at is None


# --- ProviderConfig ---

class TestProviderConfig:
    def test_defaults(self):
        c = ProviderConfig()
        assert c.name == "ollama"
        assert c.base_url == "http://localhost:11434"
        assert c.model == "llama3.2"
        assert c.temperature == 0.7
        assert c.max_tokens == 4096


# --- GuildConfig ---

class TestGuildConfig:
    def test_defaults(self):
        c = GuildConfig()
        assert c.default_permission == PermissionTier.ASK
        assert c.max_concurrent_agents == 1
        assert c.max_concurrent_tool_calls == 4
        assert c.autonomy_timeout_minutes is None

    def test_entry_agent_defaults(self):
        c = GuildConfig()
        assert c.entry_agent.name == "guild-master"
        assert c.entry_agent.role == "orchestrator"
        assert c.entry_agent.permission == PermissionTier.SCOPED
        assert "spawn_agent" in c.entry_agent.tools
        assert "Guild Master" in c.entry_agent.system_prompt
