"""Tests for agent/loop.py — the core agent loop (REQ-06.8)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from guild.agent.loop import AgentLoop
from guild.provider.base import LLMResponse
from guild.tools.base import ToolResult


def _make_provider(*responses: LLMResponse) -> AsyncMock:
    """Create a mock provider that returns responses in sequence."""
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=list(responses))
    return provider


def _make_tool_executors() -> dict:
    """Create mock tool executors for file_read and file_write."""

    async def mock_file_write(args: dict, working_dir: str | None = None) -> ToolResult:
        return ToolResult(success=True, output=f"Wrote {len(args.get('content', ''))} chars")

    async def mock_file_read(args: dict, working_dir: str | None = None) -> ToolResult:
        return ToolResult(success=True, output="file contents here")

    return {
        "file_write": mock_file_write,
        "file_read": mock_file_read,
    }


@pytest.mark.unit
@pytest.mark.req("REQ-06.8")
class TestLoopBasics:
    """Core loop mechanics: exit conditions, tool execution, message flow."""

    async def test_loop_exits_on_text_only_response(self) -> None:
        """If the model returns text without tool calls, the loop exits."""
        provider = _make_provider(
            LLMResponse(content="Done! The task is complete.", tool_calls=None)
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="You are helpful.", user_input="Say hi")
        assert result == "Done! The task is complete."

    async def test_loop_executes_tool_and_returns_final_text(self) -> None:
        """Loop calls tool, then model responds with final text."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "x.txt", "content": "hi"},
                        }
                    }
                ],
            ),
            LLMResponse(content="Done, file written.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="You help.", user_input="Write hi to x.txt")
        assert "Done" in result

    async def test_loop_stops_after_max_turns(self) -> None:
        """Loop stops if max_turns is reached, even if model keeps calling tools."""
        # Model always calls a tool — should stop after 3 turns
        infinite_tool_response = LLMResponse(
            content="",
            tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
        )
        provider = _make_provider(
            infinite_tool_response,
            infinite_tool_response,
            infinite_tool_response,
            LLMResponse(content="final", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors(), max_turns=3)
        await loop.run(system_prompt="sys", user_input="read a.txt")
        # Should have stopped at max_turns; provider called at most max_turns times
        assert provider.generate.call_count <= 3

    async def test_loop_feeds_tool_result_back_to_model(self) -> None:
        """After executing a tool, the result is appended to messages."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_read",
                            "arguments": {"path": "a.txt"},
                        }
                    }
                ],
            ),
            LLMResponse(content="The file has: file contents here", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="read a.txt")

        # Check the second generate call includes a tool result message
        second_call_messages = provider.generate.call_args_list[1][0][0]
        tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "file contents here" in tool_msgs[0]["content"]

    async def test_loop_handles_unknown_tool_gracefully(self) -> None:
        """Unknown tool name produces an error message, doesn't crash."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "unknown_tool", "arguments": {"x": 1}}}],
            ),
            LLMResponse(content="Sorry, I cannot do that.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="do something")
        # Should not crash, should return final text
        assert "Sorry" in result or result != ""


@pytest.mark.unit
@pytest.mark.req("REQ-06.8")
class TestLoopEdgeCases:
    """Edge cases: multiple tool calls, failures mid-sequence, exceptions."""

    async def test_loop_executes_multiple_tool_calls_in_single_response(self) -> None:
        """Model returns multiple tool calls in one response — all are executed."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}},
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "b.txt", "content": "data"},
                        }
                    },
                ],
            ),
            LLMResponse(content="Both done.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="do both")
        assert "Both done" in result
        # Both tool results should be in messages
        tool_msgs = [m for m in loop.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 2

    async def test_loop_continues_after_tool_failure_mid_sequence(self) -> None:
        """If one tool in a batch fails, the loop continues (doesn't crash)."""

        async def failing_read(args: dict, working_dir: str | None = None) -> ToolResult:
            return ToolResult(success=False, output="", error="File not found")

        async def mock_write(args: dict, working_dir: str | None = None) -> ToolResult:
            return ToolResult(success=True, output="Wrote file")

        executors = {"file_read": failing_read, "file_write": mock_write}

        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {"function": {"name": "file_read", "arguments": {"path": "x.txt"}}},
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "y.txt", "content": "hi"},
                        }
                    },
                ],
            ),
            LLMResponse(content="Handled the error.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=executors)
        result = await loop.run(system_prompt="sys", user_input="read and write")
        assert "Handled" in result
        tool_msgs = [m for m in loop.messages if m.get("role") == "tool"]
        # Both tools produced a message
        assert len(tool_msgs) == 2

    async def test_loop_handles_tool_executor_exception(self) -> None:
        """If a tool executor raises an unexpected exception, loop doesn't crash."""

        async def exploding_tool(args: dict, working_dir: str | None = None) -> ToolResult:
            raise RuntimeError("Unexpected internal error")

        executors = {
            "file_read": exploding_tool,
            "file_write": _make_tool_executors()["file_write"],
        }

        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}},
                ],
            ),
            LLMResponse(content="I see the error.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=executors)
        result = await loop.run(system_prompt="sys", user_input="read file")
        # Should not crash, should get final text
        assert result == "I see the error."
        # The tool error message should be in history
        tool_msgs = [m for m in loop.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "failed" in tool_msgs[0]["content"].lower()

    async def test_loop_returns_empty_string_on_max_turns_with_no_text(self) -> None:
        """If max_turns hit and model never gave text content, return empty."""
        tool_response = LLMResponse(
            content="",
            tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
        )
        provider = _make_provider(tool_response, tool_response)
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors(), max_turns=2)
        result = await loop.run(system_prompt="sys", user_input="loop forever")
        assert result == ""

    async def test_loop_builds_correct_message_sequence(self) -> None:
        """Messages follow: system, user, assistant, tool, [nudge], assistant."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "x.txt", "content": "hi"},
                        }
                    }
                ],
            ),
            LLMResponse(content="Done.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="write")

        roles = [m["role"] for m in loop.messages]
        assert roles[0] == "system"
        assert roles[1] == "user"
        assert roles[2] == "assistant"
        assert roles[3] == "tool"
        # May have a nudge (user role) then assistant
        assert roles[-1] == "assistant"


@pytest.mark.unit
@pytest.mark.req("REQ-06.8")
class TestLoopCompletionHeuristics:
    """Integration of completion heuristics into the loop."""

    async def test_loop_dedup_prevents_repeated_identical_calls(self) -> None:
        """Identical tool calls on consecutive turns are skipped (Fix C)."""
        same_call = {
            "function": {
                "name": "file_write",
                "arguments": {"path": "x.txt", "content": "hi"},
            }
        }
        provider = _make_provider(
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),  # duplicate
            LLMResponse(content="All done.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="write file")

        # The second time, a dedup message is injected instead
        all_messages = loop.messages
        dedup_msgs = [m for m in all_messages if "already" in m.get("content", "").lower()]
        assert len(dedup_msgs) >= 1

    async def test_loop_injects_completion_nudge_after_success(self) -> None:
        """After a single successful tool execution, a nudge is injected."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "x.txt", "content": "hi"},
                        }
                    }
                ],
            ),
            LLMResponse(content="Task complete.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="write file")

        # Check that a nudge message was injected
        all_messages = loop.messages
        nudge_found = any(
            "summarize" in m.get("content", "").lower()
            or "complete" in m.get("content", "").lower()
            for m in all_messages
            if m.get("role") == "user" and m != all_messages[1]
        )
        assert nudge_found


@pytest.mark.unit
@pytest.mark.req("REQ-06.9")
class TestMultiTurnConversation:
    """Tests for send() — multi-turn conversation support."""

    async def test_send_preserves_conversation_history(self) -> None:
        """send() appends to existing messages rather than resetting."""
        provider = _make_provider(
            # Response to run()
            LLMResponse(content="Hello! How can I help?", tool_calls=None),
            # Response to send()
            LLMResponse(content="Your name is Alice.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        await loop.run(system_prompt="You are helpful.", user_input="My name is Alice.")
        result = await loop.send("What is my name?")

        assert result == "Your name is Alice."
        # Verify system prompt is still at the start
        assert loop.messages[0]["role"] == "system"
        assert loop.messages[0]["content"] == "You are helpful."
        # Verify both user messages are present
        user_msgs = [m for m in loop.messages if m.get("role") == "user"]
        assert len(user_msgs) >= 2
        assert any("Alice" in m["content"] for m in user_msgs)
        assert any("name" in m["content"] for m in user_msgs)

    async def test_send_after_run_maintains_context(self) -> None:
        """send() sees tool results from the initial run()."""
        provider = _make_provider(
            # run(): tool call then final response
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
            ),
            LLMResponse(content="The file contains: file contents here", tool_calls=None),
            # send(): response referencing prior context
            LLMResponse(content="Yes, the file had: file contents here", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        await loop.run(system_prompt="You are helpful.", user_input="Read a.txt")
        result = await loop.send("What did the file contain?")

        assert "file contents here" in result
        # The generate call for send() should include the full history
        final_call_messages = provider.generate.call_args_list[-1][0][0]
        # Should include system, user, assistant, tool, assistant, user
        roles = [m["role"] for m in final_call_messages]
        assert roles[0] == "system"
        assert "tool" in roles  # tool result from run() is preserved

    async def test_multiple_sends_accumulate_messages(self) -> None:
        """Multiple send() calls accumulate all messages in history."""
        provider = _make_provider(
            LLMResponse(content="Response 1", tool_calls=None),
            LLMResponse(content="Response 2", tool_calls=None),
            LLMResponse(content="Response 3", tool_calls=None),
            LLMResponse(content="Response 4", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        await loop.run(system_prompt="sys", user_input="msg1")
        await loop.send("msg2")
        await loop.send("msg3")
        result = await loop.send("msg4")

        assert result == "Response 4"
        # Should have 4 user messages and 4 assistant messages
        user_msgs = [m for m in loop.messages if m["role"] == "user"]
        assistant_msgs = [m for m in loop.messages if m["role"] == "assistant"]
        assert len(user_msgs) == 4
        assert len(assistant_msgs) == 4

    async def test_run_resets_but_send_does_not(self) -> None:
        """run() resets conversation; send() preserves it."""
        provider = _make_provider(
            LLMResponse(content="First run response", tool_calls=None),
            LLMResponse(content="After send", tool_calls=None),
            # Second run() resets everything
            LLMResponse(content="Second run response", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        await loop.run(system_prompt="sys1", user_input="first")
        await loop.send("follow-up")

        # At this point we should have 2 user messages
        user_msgs_before = [m for m in loop.messages if m["role"] == "user"]
        assert len(user_msgs_before) == 2

        # Now run() resets
        await loop.run(system_prompt="sys2", user_input="fresh start")

        # After run(), only 1 user message (the new one)
        user_msgs_after = [m for m in loop.messages if m["role"] == "user"]
        assert len(user_msgs_after) == 1
        assert user_msgs_after[0]["content"] == "fresh start"
        # System prompt changed
        assert loop.messages[0]["content"] == "sys2"

    async def test_send_without_run_raises_error(self) -> None:
        """send() before run() raises RuntimeError."""
        provider = _make_provider(
            LLMResponse(content="Nope", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        with pytest.raises(RuntimeError, match="run.*before"):
            await loop.send("hello")

    async def test_send_resets_recent_tool_calls_per_turn(self) -> None:
        """send() resets recent_tool_calls to avoid stale dedup state."""
        same_call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        provider = _make_provider(
            # run(): calls file_read
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="Read it.", tool_calls=None),
            # send(): calls file_read again — should NOT be deduped
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="Read it again.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())

        await loop.run(system_prompt="sys", user_input="read a.txt")
        result = await loop.send("read a.txt again")

        assert result == "Read it again."
        # The tool should have been executed (not deduped)
        tool_msgs = [m for m in loop.messages if m["role"] == "tool"]
        # Should have 2 real tool results (not dedup messages)
        real_tool_msgs = [m for m in tool_msgs if "already" not in m.get("content", "").lower()]
        assert len(real_tool_msgs) == 2


@pytest.mark.integration
@pytest.mark.req("REQ-06.8")
class TestRealOllama:
    """Integration test using the real Ollama instance."""

    async def test_real_ollama_creates_file_without_looping(self, tmp_path) -> None:
        """Full integration: model calls file_write, loop completes."""
        from guild.provider.ollama import create_provider
        from guild.tools.file_ops import execute_file_read, execute_file_write

        provider = create_provider(
            base_url="http://192.168.0.110:11434",
            model="gemma4-26b-moe-agent",
        )

        # Check connectivity
        healthy = await provider.health_check()
        if not healthy:
            pytest.skip("Ollama not reachable at http://192.168.0.110:11434")

        tool_executors = {
            "file_read": execute_file_read,
            "file_write": execute_file_write,
        }

        loop = AgentLoop(
            provider=provider,
            tool_executors=tool_executors,
            working_dir=str(tmp_path),
            max_turns=5,
        )

        result = await loop.run(
            system_prompt=(
                "You are a helpful coding assistant. Use the available tools "
                "to complete tasks. After completing an action successfully, "
                "provide a brief summary response."
            ),
            user_input=(
                "Create a file called hello.txt with the content "
                "'Hello, Guild!' in the working directory."
            ),
        )

        # Verify the file was created
        target_file = tmp_path / "hello.txt"
        assert target_file.exists(), f"File not created. Loop result: {result}"
        content = target_file.read_text()
        assert "Hello, Guild!" in content

        # Verify loop completed efficiently (not stuck looping)
        generate_count = len([m for m in loop.messages if m.get("role") == "assistant"])
        assert generate_count <= 3, (
            f"Loop took {generate_count} turns — expected <= 3. "
            f"Messages: {[m.get('role') for m in loop.messages]}"
        )

        # Verify no duplicate tool calls
        tool_calls_seen: list[dict] = []
        for msg in loop.messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    assert tc not in tool_calls_seen, f"Duplicate tool call detected: {tc}"
                    tool_calls_seen.append(tc)
