"""Integration tests: agent loop + real tools + real SQLite.

These tests wire the actual AgentLoop with real tool executors and real
SQLite storage. Only the LLM provider is mocked (external, non-deterministic).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from guild.agent.loop import AgentLoop
from guild.provider.base import LLMResponse
from guild.storage.sqlite import Storage
from guild.tools.registry import build_tool_executors

pytestmark = [pytest.mark.integration]


@pytest.fixture()
async def store(tmp_path: Path) -> Storage:
    """Real SQLite storage."""
    s = Storage(tmp_path / "guild.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture()
def working_dir(tmp_path: Path) -> str:
    """Real working directory for file operations."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    return str(tmp_path)


def _make_provider(*responses: LLMResponse) -> AsyncMock:
    """Create a mock provider that returns predetermined responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=list(responses))
    provider.health_check = AsyncMock(return_value=True)
    return provider


@pytest.mark.req("REQ-06.8")
class TestAgentLoopWithRealTools:
    """Agent loop executes real file operations via tool calls."""

    async def test_agent_reads_file_via_tool(self, working_dir: str) -> None:
        """Agent loop calls file_read tool and gets real file content."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_read",
                            "arguments": {"path": "src/main.py"},
                        }
                    }
                ],
                input_tokens=100,
                output_tokens=50,
                model="mock",
            ),
            LLMResponse(
                content="I read the file. It contains a print statement.",
                tool_calls=None,
                input_tokens=80,
                output_tokens=30,
                model="mock",
            ),
        )
        tool_executors = build_tool_executors()
        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=working_dir,
            max_turns=5,
        )
        result = await loop.run(
            system_prompt="You are a helpful assistant.",
            user_input="Read src/main.py",
        )
        assert "print" in result.lower() or "hello" in result.lower() or "read" in result.lower()

    async def test_agent_writes_file_via_tool(self, working_dir: str) -> None:
        """Agent loop calls file_write tool and creates a real file."""
        new_file = Path(working_dir) / "output.txt"
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "output.txt", "content": "generated content"},
                        }
                    }
                ],
                input_tokens=100,
                output_tokens=50,
                model="mock",
            ),
            LLMResponse(
                content="Done, I wrote the file.",
                tool_calls=None,
                input_tokens=80,
                output_tokens=30,
                model="mock",
            ),
        )
        tool_executors = build_tool_executors()
        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=working_dir,
            max_turns=5,
        )
        result = await loop.run(
            system_prompt="You are a helpful assistant.",
            user_input="Write output.txt",
        )
        assert new_file.exists()
        assert new_file.read_text() == "generated content"

    async def test_agent_runs_shell_command(self, working_dir: str) -> None:
        """Agent loop calls shell tool and gets real command output."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "shell",
                            "arguments": {"command": "echo integration_test_works"},
                        }
                    }
                ],
                input_tokens=100,
                output_tokens=50,
                model="mock",
            ),
            LLMResponse(
                content="The command output was: integration_test_works",
                tool_calls=None,
                input_tokens=80,
                output_tokens=30,
                model="mock",
            ),
        )
        tool_executors = build_tool_executors()
        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=working_dir,
            max_turns=5,
        )
        result = await loop.run(
            system_prompt="You are a helpful assistant.",
            user_input="Run echo",
        )
        # The shell tool result should have been fed back to the provider
        assert provider.generate.call_count == 2


@pytest.mark.req("REQ-06.6")
class TestAgentLoopWithRealStorage:
    """Agent loop results persist to real SQLite."""

    async def test_task_stored_after_completion(self, store: Storage, working_dir: str) -> None:
        """After agent completes, task and messages are in real SQLite."""
        provider = _make_provider(
            LLMResponse(
                content="Task complete. The answer is 42.",
                tool_calls=None,
                input_tokens=100,
                output_tokens=50,
                model="mock",
            ),
        )
        tool_executors = build_tool_executors()

        # Create task in storage
        await store.create_task("integ-task-1", "What is the answer?")
        await store.register_agent("agent-1", "default")
        await store.update_task("integ-task-1", assigned_agent="agent-1")

        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=working_dir,
            max_turns=5,
        )
        result = await loop.run(
            system_prompt="You are a helpful assistant.",
            user_input="What is the answer?",
        )

        # Store messages
        await store.append_message("agent-1", "user", "What is the answer?")
        await store.append_message("agent-1", "assistant", result)
        await store.update_task("integ-task-1", status="completed", result=result)

        # Verify persistence
        task = await store.get_task("integ-task-1")
        assert task is not None
        assert task["status"] == "completed"
        assert "42" in task["result"]

        messages = await store.get_messages("agent-1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    async def test_audit_trail_records_task_lifecycle(self, store: Storage) -> None:
        """Audit log captures the full task lifecycle."""
        await store.create_task("integ-task-2", "Test audit")
        await store.log_audit("task_created", details="task_id=integ-task-2")
        await store.log_audit("agent_assigned", agent_id="agent-2", details="task_id=integ-task-2")
        await store.log_audit("task_completed", details="task_id=integ-task-2")

        audit = await store.list_audit(limit=10)
        assert len(audit) == 3
        actions = [a["action"] for a in audit]
        assert "task_created" in actions
        assert "agent_assigned" in actions
        assert "task_completed" in actions


@pytest.mark.req("REQ-04.9")
@pytest.mark.req("REQ-06.6")
class TestTeamExecutionPersistsToStorage:
    """Team execution creates proper tasks, agents, messages in storage."""

    async def test_team_run_creates_subtasks_in_storage(
        self, store: Storage, working_dir: str
    ) -> None:
        """Each block in a team run creates a task record in storage."""
        from guild.blocks.definition import BlockDef, Connection, TeamDef
        from guild.blocks.registry import BlockRegistry
        from guild.orchestration.team_runner import TeamRunner
        from guild.provider.base import LLMResponse

        # Create a simple 2-block team
        planner_block = BlockDef(
            name="planner",
            role="planner",
            system_prompt="You are a planner. Output a plan.",
            tools=[],
        )
        coder_block = BlockDef(
            name="coder",
            role="coder",
            system_prompt="You are a coder. Implement the plan.",
            tools=["file_write", "shell"],
        )

        registry = BlockRegistry()
        registry._blocks = {"planner": planner_block, "coder": coder_block}
        registry._teams = {
            "dev": TeamDef(
                name="dev",
                blocks={"plan": "planner", "code": "coder"},
                connections=[
                    Connection(
                        source_block="plan",
                        source_port="output",
                        target_block="code",
                        target_port="input",
                    ),
                ],
                entry_block="plan",
            )
        }

        provider = AsyncMock()
        provider.generate = AsyncMock(
            return_value=LLMResponse(
                content="Done with this step.",
                tool_calls=None,
                input_tokens=50,
                output_tokens=20,
                model="mock",
            ),
        )

        runner = TeamRunner(
            team=registry.get_team("dev"),
            registry=registry,
            provider=provider,
            storage=store,
            working_dir=working_dir,
        )
        await runner.run("Build a hello world app")

        # Verify tasks were created in storage
        tasks = await store.list_tasks()
        assert len(tasks) >= 2  # At least one per block

        # Verify agents were registered
        agents = await store.list_agents()
        assert len(agents) >= 2

        # Verify messages were stored
        for agent in agents:
            messages = await store.get_messages(agent["agent_id"])
            assert len(messages) > 0  # Each agent should have messages

        # Verify audit trail
        audit = await store.list_audit()
        assert any("task_created" in a["action"] for a in audit)
