"""Tests for interactive chat session persistence (REQ-05, REQ-07.1)."""

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


class TestMultiTurnChat:
    """REQ-05, REQ-07.1: Chat should support multi-turn conversation."""

    async def test_multi_turn_preserves_context(self, storage):
        """Agent should see all previous messages in subsequent turns."""
        provider = make_provider([
            LLMResponse(content="Hello! How can I help?"),
            LLMResponse(content="Your name is Alice, you told me."),
        ])
        block = BlockDef(name="test", role="test", system_prompt="Be helpful.", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()

        await agent.run("My name is Alice")
        await agent.run("What is my name?")

        # Second call should have received all previous messages
        second_call_msgs = provider.generate.call_args_list[1].args[0]
        contents = [m.content for m in second_call_msgs]
        assert "My name is Alice" in contents
        assert "Hello! How can I help?" in contents
        assert "What is my name?" in contents

    async def test_multi_turn_messages_all_persisted(self, storage):
        """All messages from all turns should be in DB."""
        provider = make_provider([
            LLMResponse(content="Response 1"),
            LLMResponse(content="Response 2"),
            LLMResponse(content="Response 3"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()

        await agent.run("Turn 1")
        await agent.run("Turn 2")
        await agent.run("Turn 3")

        msgs = await storage.get_messages("a1")
        # system + (user + assistant) * 3 = 7
        assert len(msgs) == 7
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert len(user_msgs) == 3

    async def test_token_accumulation_across_turns(self, storage):
        """Tokens should accumulate across multiple run() calls."""
        provider = make_provider([
            LLMResponse(content="r1", input_tokens=10, output_tokens=5),
            LLMResponse(content="r2", input_tokens=20, output_tokens=10),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=[])
        agent = AgentLoop("a1", block, provider, storage)
        await agent.initialize()

        await agent.run("turn 1")
        await agent.run("turn 2")

        assert agent.total_input_tokens == 30
        assert agent.total_output_tokens == 15
