"""Tests for checkpoint/resume functionality (REQ-06.7, REQ-07.2)."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.agent import AgentLoop
from guild.core.models import BlockDef, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    """Create a test storage instance."""
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(responses: list[LLMResponse]) -> AsyncMock:
    """Create a mock provider returning responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=responses)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestCheckpoint:
    """REQ-06.7: Agent state checkpointed to DB, resumable after restart."""

    async def test_messages_persisted_after_each_turn(self, storage):
        """Every message should be in DB immediately, not just at end."""
        provider = make_provider([
            LLMResponse(
                content="",
                tool_calls=[{"id": "c0", "function": {"name": "file_read", "arguments": {"path": "/dev/null"}}}],
            ),
            LLMResponse(content="done"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop("a1", block, provider, storage, permission_checker=checker)
        await agent.initialize()
        await agent.run("do something")

        msgs = await storage.get_messages("a1")
        roles = [m["role"] for m in msgs]
        # Should have: system, user, assistant (tool call), tool, assistant (final)
        assert "system" in roles
        assert "user" in roles
        assert "tool" in roles
        assert roles.count("assistant") == 2

    async def test_agent_status_tracked_in_db(self, storage):
        """Agent status should be updated in DB during execution."""
        provider = make_provider([LLMResponse(content="done")])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()
        await agent.run("hi")

        agents = await storage.list_agents()
        assert agents[0]["status"] == "done"

    async def test_token_counts_persisted(self, storage):
        """Token usage should be saved to DB."""
        provider = make_provider([
            LLMResponse(content="response", input_tokens=100, output_tokens=50),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()
        await agent.run("hi")

        agents = await storage.list_agents()
        assert int(agents[0]["token_input"]) == 100
        assert int(agents[0]["token_output"]) == 50

    async def test_resume_agent_from_stored_messages(self, storage):
        """REQ-07.2: Should be able to reconstruct agent state from DB messages."""
        # First run — agent does some work
        provider1 = make_provider([LLMResponse(content="first response")])
        block = BlockDef(name="test", role="test", system_prompt="Be helpful.", tools=[])
        agent1 = AgentLoop("a1", block, provider1, storage)
        await agent1.initialize()
        await agent1.run("hello")

        # Verify messages are in DB
        stored_msgs = await storage.get_messages("a1")
        assert len(stored_msgs) >= 3  # system + user + assistant

        # Second run — new agent, same ID, loads history
        provider2 = make_provider([LLMResponse(content="resumed response")])
        agent2 = AgentLoop("a1-resumed", block, provider2, storage)
        await agent2.initialize()

        # Load previous messages into new agent's context
        from guild.core.models import Message
        for msg in stored_msgs:
            agent2.messages.append(Message(role=msg["role"], content=msg["content"]))

        await agent2.run("continue from where we left off")

        # The provider should have received all previous messages + new one
        call_args = provider2.generate.call_args
        messages_sent = call_args.args[0]
        # Should include the original system + user + assistant + new user
        assert len(messages_sent) > 3
