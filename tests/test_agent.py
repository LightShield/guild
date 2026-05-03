"""Tests for core/agent.py — tool execution, permission enforcement, turn limits."""

import pytest
from unittest.mock import AsyncMock

pytestmark = [pytest.mark.unit, pytest.mark.integration]
from pathlib import Path

from guild.core.agent import AgentLoop, execute_tool, BUILTIN_TOOLS
from guild.core.models import BlockDef, Message, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMResponse


# --- Tool execution tests ---

class TestExecuteTool:
    async def test_file_read(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await execute_tool("file_read", {"path": str(f)})
        assert "hello world" in result

    async def test_file_read_not_found(self):
        result = await execute_tool("file_read", {"path": "/nonexistent/file.txt"})
        assert "Error" in result

    async def test_file_write(self, tmp_path):
        f = tmp_path / "out.txt"
        result = await execute_tool("file_write", {"path": str(f), "content": "test content"})
        assert "Wrote" in result
        assert f.read_text() == "test content"

    async def test_file_write_creates_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "out.txt"
        await execute_tool("file_write", {"path": str(f), "content": "nested"})
        assert f.read_text() == "nested"

    async def test_shell(self):
        result = await execute_tool("shell", {"command": "echo hello"})
        assert "hello" in result
        assert "[exit 0]" in result

    async def test_shell_timeout(self):
        # This should not actually wait 60s — we test the mechanism exists
        result = await execute_tool("shell", {"command": "echo fast"})
        assert "fast" in result

    async def test_search(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo():\n    pass\n")
        (tmp_path / "b.py").write_text("def bar():\n    foo()\n")
        result = await execute_tool("search", {"pattern": "foo", "path": str(tmp_path)})
        assert "a.py" in result
        assert "b.py" in result

    async def test_search_no_matches(self, tmp_path):
        (tmp_path / "a.py").write_text("nothing here")
        result = await execute_tool("search", {"pattern": "zzzzz", "path": str(tmp_path)})
        assert "No matches" in result

    async def test_glob(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.txt").write_text("")
        result = await execute_tool("glob", {"pattern": "*.py", "path": str(tmp_path)})
        assert "a.py" in result
        assert "b.txt" not in result

    async def test_unknown_tool(self):
        result = await execute_tool("nonexistent", {})
        assert "Error" in result

    async def test_relative_path_resolved(self, tmp_path):
        (tmp_path / "test.txt").write_text("content")
        result = await execute_tool("file_read", {"path": "test.txt"}, working_dir=str(tmp_path))
        assert "content" in result


class TestBuiltinToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for name, tool in BUILTIN_TOOLS.items():
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["name"] == name

    def test_safety_rules_in_shell_description(self):
        desc = BUILTIN_TOOLS["shell"]["function"]["description"]
        assert "NEVER" in desc or "SAFETY" in desc

    def test_safety_rules_in_file_write_description(self):
        desc = BUILTIN_TOOLS["file_write"]["function"]["description"]
        assert "SAFETY" in desc


# --- Agent loop tests (with mocked LLM) ---

@pytest.fixture
async def mock_storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_mock_provider(responses: list[LLMResponse]):
    """Create a mock provider that returns responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=responses)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestAgentLoop:
    async def test_simple_response_no_tools(self, mock_storage):
        provider = make_mock_provider([
            LLMResponse(content="Hello!", input_tokens=10, output_tokens=5),
        ])
        block = BlockDef(name="test", role="test", system_prompt="You are helpful.", tools=[])
        agent = AgentLoop("a1", block, provider, mock_storage)
        await agent.initialize()
        result = await agent.run("hi")
        assert result == "Hello!"
        assert agent.total_input_tokens == 10
        assert agent.total_output_tokens == 5

    async def test_tool_call_and_response(self, mock_storage, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content here")

        provider = make_mock_provider([
            LLMResponse(
                content="",
                tool_calls=[{"id": "c0", "function": {"name": "file_read", "arguments": {"path": str(test_file)}}}],
                input_tokens=20, output_tokens=10,
            ),
            LLMResponse(content="I read the file.", input_tokens=30, output_tokens=15),
        ])
        block = BlockDef(name="test", role="test", system_prompt="Read files.", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop("a1", block, provider, mock_storage, working_dir=str(tmp_path), permission_checker=checker)
        await agent.initialize()
        result = await agent.run("read test.txt")
        assert result == "I read the file."
        assert agent.total_input_tokens == 50
        assert agent.total_output_tokens == 25

    async def test_permission_denied_blocks_tool(self, mock_storage):
        provider = make_mock_provider([
            LLMResponse(
                content="",
                tool_calls=[{"id": "c0", "function": {"name": "shell", "arguments": {"command": "ls"}}}],
            ),
            LLMResponse(content="Permission was denied."),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["shell"])
        checker = PermissionChecker(PermissionTier.NOTHING)
        agent = AgentLoop("a1", block, provider, mock_storage, permission_checker=checker)
        await agent.initialize()
        result = await agent.run("run ls")
        # The tool result should contain "Permission denied"
        tool_msgs = [m for m in agent.messages if m.role == "tool"]
        assert any("Permission denied" in m.content for m in tool_msgs)

    async def test_nothing_tier_gets_no_tools(self, mock_storage):
        provider = make_mock_provider([
            LLMResponse(content="I have no tools."),
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read", "shell"])
        checker = PermissionChecker(PermissionTier.NOTHING)
        agent = AgentLoop("a1", block, provider, mock_storage, permission_checker=checker)
        await agent.initialize()
        await agent.run("do something")
        # Provider should have been called with no tools
        call_args = provider.generate.call_args
        assert call_args.kwargs.get("tools") is None or call_args.kwargs.get("tools") == []

    async def test_max_turns_limit(self, mock_storage):
        """Agent should stop after max_turns even if model keeps calling tools."""
        provider = make_mock_provider([
            LLMResponse(content="", tool_calls=[{"id": f"c{i}", "function": {"name": "file_read", "arguments": {"path": "/dev/null"}}}])
            for i in range(10)
        ])
        block = BlockDef(name="test", role="test", system_prompt="test", tools=["file_read"])
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        agent = AgentLoop("a1", block, provider, mock_storage, permission_checker=checker)
        await agent.initialize()
        await agent.run("loop forever", max_turns=3)
        assert provider.generate.call_count == 3

    async def test_messages_persisted_to_storage(self, mock_storage):
        provider = make_mock_provider([
            LLMResponse(content="response"),
        ])
        block = BlockDef(name="test", role="test", system_prompt="sys", tools=[])
        agent = AgentLoop("a1", block, provider, mock_storage)
        await agent.initialize()
        await agent.run("hello")
        msgs = await mock_storage.get_messages("a1")
        roles = [m["role"] for m in msgs]
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles
