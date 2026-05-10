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


@pytest.mark.unit
@pytest.mark.req("REQ-06.4")
class TestStuckRecovery:
    """Tests for stuck recovery — try alternatives before escalating."""

    async def test_stuck_triggers_recovery_prompt(self) -> None:
        """Model gets stuck, recovery prompt is injected, model gets another chance."""
        from guild.agent.loop import STUCK_RECOVERY_PROMPT
        from guild.agent.stuck import StuckDetector

        # Model repeats the same call 3 times (triggers stuck), then after
        # recovery prompt, produces text.
        same_call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        provider = _make_provider(
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            # After recovery prompt injection:
            LLMResponse(content="Let me try a different approach.", tool_calls=None),
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=10,
        )
        result = await loop.run(system_prompt="sys", user_input="read a.txt")

        # Recovery prompt should have been injected
        user_msgs = [m for m in loop.messages if m["role"] == "user"]
        recovery_msgs = [m for m in user_msgs if STUCK_RECOVERY_PROMPT in m["content"]]
        assert len(recovery_msgs) == 1
        assert result == "Let me try a different approach."

    async def test_recovery_success_continues_normally(self) -> None:
        """After recovery prompt, model produces good output and loop continues."""
        from guild.agent.stuck import StuckDetector

        same_call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        different_call = {
            "function": {"name": "file_write", "arguments": {"path": "b.txt", "content": "x"}}
        }
        provider = _make_provider(
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            # After recovery: model tries a different tool
            LLMResponse(content="", tool_calls=[different_call]),
            LLMResponse(content="Fixed it!", tool_calls=None),
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=10,
        )
        result = await loop.run(system_prompt="sys", user_input="do something")
        assert result == "Fixed it!"

    async def test_double_stuck_escalates(self) -> None:
        """Recovery attempted, still stuck — escalation produced."""
        from guild.agent.stuck import StuckDetector

        same_call = {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        provider = _make_provider(
            # First stuck (3 identical calls)
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            # After recovery prompt — still stuck (3 more identical calls)
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
            LLMResponse(content="", tool_calls=[same_call]),
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run(system_prompt="sys", user_input="read a.txt")

        # Should return escalation message
        assert "stuck" in result.lower() or "need help" in result.lower()
        assert "read a.txt" in result  # task description present


@pytest.mark.unit
@pytest.mark.req("REQ-06.5")
class TestHumanEscalation:
    """Tests for structured escalation messages."""

    async def test_escalation_includes_task_description(self) -> None:
        """Escalation message includes the original task."""
        from guild.agent.stuck import StuckDetector

        same_call = {"function": {"name": "file_read", "arguments": {"path": "x.py"}}}
        provider = _make_provider(
            *[LLMResponse(content="", tool_calls=[same_call]) for _ in range(6)],
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run(system_prompt="sys", user_input="Refactor the database module")

        assert "Refactor the database module" in result

    async def test_escalation_includes_stuck_reason(self) -> None:
        """Escalation message includes the reason from stuck detector."""
        from guild.agent.stuck import StuckDetector

        same_call = {"function": {"name": "file_read", "arguments": {"path": "x.py"}}}
        provider = _make_provider(
            *[LLMResponse(content="", tool_calls=[same_call]) for _ in range(6)],
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run(system_prompt="sys", user_input="Do task X")

        # Should contain the stuck reason
        assert "stuck" in result.lower() or "repeated" in result.lower()

    async def test_escalation_includes_what_was_tried(self) -> None:
        """Escalation message includes what tools were attempted."""
        from guild.agent.stuck import StuckDetector

        same_call = {"function": {"name": "file_read", "arguments": {"path": "x.py"}}}
        provider = _make_provider(
            *[LLMResponse(content="", tool_calls=[same_call]) for _ in range(6)],
        )
        detector = StuckDetector(max_repeated_calls=3)
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            stuck_detector=detector,
            max_turns=20,
        )
        result = await loop.run(system_prompt="sys", user_input="Fix the bug")

        # Should mention what was tried (tool name)
        assert "file_read" in result


@pytest.mark.unit
@pytest.mark.req("REQ-06.10")
class TestAdversarialSelfReview:
    """Tests for adversarial self-review after successful task completion."""

    async def test_self_review_runs_after_successful_task(self) -> None:
        """After task completes, self-review prompt is injected."""
        from guild.agent.loop import SELF_REVIEW_PROMPT

        provider = _make_provider(
            # Normal task completion
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "x.py", "content": "code"},
                        }
                    }
                ],
            ),
            LLMResponse(content="Done writing file.", tool_calls=None),
            # Self-review response
            LLMResponse(content="Reviewed. Everything looks correct.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="Write code", self_review=True)

        # The self-review prompt should have been injected
        user_msgs = [m for m in loop.messages if m["role"] == "user"]
        review_msgs = [m for m in user_msgs if SELF_REVIEW_PROMPT in m["content"]]
        assert len(review_msgs) == 1
        assert result == "Reviewed. Everything looks correct."

    async def test_self_review_skipped_when_disabled(self) -> None:
        """Self-review is not run when self_review=False (default)."""
        from guild.agent.loop import SELF_REVIEW_PROMPT

        provider = _make_provider(
            LLMResponse(content="Task complete.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="Do task")

        # No review prompt should be in messages
        user_msgs = [m for m in loop.messages if m["role"] == "user"]
        review_msgs = [m for m in user_msgs if SELF_REVIEW_PROMPT in m["content"]]
        assert len(review_msgs) == 0
        assert result == "Task complete."

    async def test_self_review_can_trigger_additional_tool_calls(self) -> None:
        """Self-review finds an issue and makes a fix via tool call."""
        provider = _make_provider(
            # Normal task
            LLMResponse(content="File written.", tool_calls=None),
            # Self-review: finds issue, calls a tool to fix
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "x.py", "content": "fixed code"},
                        }
                    }
                ],
            ),
            LLMResponse(content="Fixed a bug I found during review.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="Write code", self_review=True)

        assert result == "Fixed a bug I found during review."
        # Should have tool calls from the review phase
        tool_msgs = [m for m in loop.messages if m["role"] == "tool"]
        assert len(tool_msgs) >= 1


@pytest.mark.unit
@pytest.mark.req("REQ-10.1")
class TestTokenTracking:
    """Tests for token usage tracking per agent loop execution."""

    async def test_tracks_input_tokens(self) -> None:
        """AgentLoop accumulates input_tokens from each LLM response."""
        provider = _make_provider(
            LLMResponse(content="Hello", tool_calls=None, input_tokens=100, output_tokens=20),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="hi")

        assert loop.total_input_tokens == 100

    async def test_tracks_output_tokens(self) -> None:
        """AgentLoop accumulates output_tokens from each LLM response."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a"}}}],
                input_tokens=50,
                output_tokens=30,
            ),
            LLMResponse(content="Done", tool_calls=None, input_tokens=80, output_tokens=40),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="read")

        assert loop.total_output_tokens == 70  # 30 + 40

    async def test_tokens_accumulate_across_multiple_turns(self) -> None:
        """Token counters accumulate correctly across many tool-call turns."""
        read_call = {"function": {"name": "file_read", "arguments": {"path": "a"}}}
        provider = _make_provider(
            LLMResponse(content="", tool_calls=[read_call], input_tokens=100, output_tokens=50),
            LLMResponse(content="", tool_calls=[read_call], input_tokens=120, output_tokens=60),
            LLMResponse(content="Done", tool_calls=None, input_tokens=130, output_tokens=70),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="read lots")

        assert loop.total_input_tokens == 350  # 100 + 120 + 130
        assert loop.total_output_tokens == 180  # 50 + 60 + 70

    async def test_tracks_tool_call_count(self) -> None:
        """AgentLoop counts total tool calls across all turns."""
        write_call = {
            "function": {"name": "file_write", "arguments": {"path": "b", "content": "x"}}
        }
        read_call = {"function": {"name": "file_read", "arguments": {"path": "a"}}}
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[read_call, write_call],
                input_tokens=10,
                output_tokens=10,
            ),
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "c"}}}],
                input_tokens=10,
                output_tokens=10,
            ),
            LLMResponse(content="Done", tool_calls=None, input_tokens=10, output_tokens=10),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="do things")

        assert loop.total_tool_calls == 3


@pytest.mark.unit
@pytest.mark.req("REQ-10.2")
class TestTokenBudget:
    """Tests for budget enforcement — stop loop when budget exceeded."""

    async def test_token_budget_stops_loop_when_exceeded(self) -> None:
        """Loop stops when cumulative tokens exceed budget."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a"}}}],
                input_tokens=500,
                output_tokens=500,
            ),
            # This response should never be reached due to budget
            LLMResponse(
                content="Should not reach",
                tool_calls=None,
                input_tokens=500,
                output_tokens=500,
            ),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            token_budget=900,  # budget < 1000 (500+500 from first call)
        )
        await loop.run(system_prompt="sys", user_input="read")

        # First call uses 1000 tokens total, exceeding budget of 900
        # Loop should stop before the second generate call
        assert loop.total_input_tokens == 500
        assert loop.total_output_tokens == 500
        assert provider.generate.call_count == 1

    async def test_budget_stops_mid_task_not_between_tasks(self) -> None:
        """Budget check happens at loop top, stopping BEFORE the next LLM call."""
        read_call = {"function": {"name": "file_read", "arguments": {"path": "a"}}}
        write_call = {
            "function": {"name": "file_write", "arguments": {"path": "b", "content": "x"}}
        }
        provider = _make_provider(
            # Turn 1: uses 600 tokens total, within budget of 700
            LLMResponse(
                content="",
                tool_calls=[read_call],
                input_tokens=300,
                output_tokens=300,
            ),
            # Turn 2: would use another 400 but budget already exceeded (600 > 700 check)
            # Actually: after turn 1 total=600 < 700 so turn 2 runs
            LLMResponse(
                content="",
                tool_calls=[write_call],
                input_tokens=200,
                output_tokens=200,
            ),
            # Turn 3: budget check at top: total=1000 > 700, loop stops
            LLMResponse(
                content="Should not reach", tool_calls=None, input_tokens=1, output_tokens=1
            ),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            token_budget=700,
        )
        result = await loop.run(system_prompt="sys", user_input="multi-step task")

        # Budget exceeded after turn 2 (total = 1000 > 700)
        # Turn 3 should NOT execute
        assert provider.generate.call_count == 2
        # Result is the empty content from turn 2's tool-call response
        assert result == ""

    async def test_zero_budget_means_unlimited(self) -> None:
        """A budget of 0 means no limit — loop runs normally."""
        read_call = {"function": {"name": "file_read", "arguments": {"path": "a"}}}
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[read_call],
                input_tokens=5000,
                output_tokens=5000,
            ),
            LLMResponse(
                content="Done",
                tool_calls=None,
                input_tokens=5000,
                output_tokens=5000,
            ),
        )
        loop = AgentLoop(
            provider=provider,
            tool_executors=_make_tool_executors(),
            token_budget=0,
        )
        result = await loop.run(system_prompt="sys", user_input="read")

        assert result == "Done"
        assert provider.generate.call_count == 2
        assert loop.total_input_tokens == 10000


@pytest.mark.unit
@pytest.mark.req("REQ-10.4")
class TestBudgetAlerts:
    """Tests for budget alerts when approaching token limits."""

    def test_budget_alert_at_80_percent(self) -> None:
        """Alert fires when usage reaches 80% of budget."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = set()
        result = check_budget_alert(8000, 10000, alerted)

        assert result is not None
        assert "80%" in result
        assert "warning" in result.lower()
        assert 0.8 in alerted

    def test_budget_alert_at_90_percent(self) -> None:
        """Alert fires when usage reaches 90% of budget."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = {0.8}  # 80% already alerted
        result = check_budget_alert(9500, 10000, alerted)

        assert result is not None
        assert "90%" in result
        assert 0.9 in alerted

    def test_budget_alert_at_100_percent(self) -> None:
        """Alert fires when usage reaches 100% of budget."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = {0.8, 0.9}  # Lower thresholds already alerted
        result = check_budget_alert(10000, 10000, alerted)

        assert result is not None
        assert "100%" in result
        assert "exceeded" in result.lower()
        assert 1.0 in alerted

    def test_no_alert_when_under_threshold(self) -> None:
        """No alert when usage is below all thresholds."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = set()
        result = check_budget_alert(5000, 10000, alerted)

        assert result is None
        assert len(alerted) == 0

    def test_no_alert_when_budget_is_zero(self) -> None:
        """Zero budget means unlimited — no alerts ever."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = set()
        result = check_budget_alert(999999, 0, alerted)

        assert result is None

    def test_alert_does_not_repeat_for_same_threshold(self) -> None:
        """Once a threshold is alerted, it does not fire again."""
        from guild.agent.budget import check_budget_alert

        alerted: set[float] = set()
        # First call at 80%
        result1 = check_budget_alert(8000, 10000, alerted)
        assert result1 is not None

        # Second call still at 80% — no new alert
        result2 = check_budget_alert(8100, 10000, alerted)
        # Should fire 90% or None depending on whether 8100/10000 >= 0.9
        # 8100/10000 = 0.81, so no 90% threshold
        assert result2 is None


@pytest.mark.unit
@pytest.mark.req("REQ-06.1")
class TestAgentDoesNotPause:
    """REQ-06.1 — agents do NOT unnecessarily pause for confirmation."""

    async def test_agent_continues_after_successful_tool_call(self) -> None:
        """After a successful tool call, the agent continues without pausing."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "function": {
                            "name": "file_write",
                            "arguments": {"path": "b.txt", "content": "data"},
                        }
                    }
                ],
            ),
            LLMResponse(content="All done.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        result = await loop.run(system_prompt="sys", user_input="read then write")

        # Loop ran through all three turns without any external prompting
        assert result == "All done."
        assert provider.generate.call_count == 3

    async def test_agent_does_not_prompt_in_scoped_mode(self) -> None:
        """In scoped mode, tools within scope proceed without prompting."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read", "file_write"],
            allowed_paths=["/project"],
        )
        # Confirm that permission checks pass without any prompt_fn
        assert checker.check("file_read", "agent-1", {"path": "/project/a.txt"}) is True
        assert (
            checker.check("file_write", "agent-1", {"path": "/project/b.txt", "content": "x"})
            is True
        )
        # No prompt function was set — meaning no pausing for confirmation


@pytest.mark.unit
@pytest.mark.req("REQ-06.7")
class TestTimeoutBehavior:
    """REQ-06.7 — timeout affects agent loop behavior."""

    async def test_timeout_zero_means_no_limit(self) -> None:
        """Timeout of 0 means unlimited — loop uses default max_turns."""
        from guild.cli.main import _compute_max_turns

        # timeout=0 should return default max turns
        result = _compute_max_turns(0)
        assert result == 50  # _DEFAULT_MAX_TURNS

    async def test_timeout_produces_partial_result(self) -> None:
        """When max_turns reached due to timeout, partial progress is returned."""
        # A very short timeout produces minimal turns
        from guild.cli.main import _compute_max_turns

        # timeout=30s => 30/10 = 3 turns (but min 5)
        result = _compute_max_turns(30)
        assert result == 5  # Minimum turns cap

        # Verify the agent loop stops at max_turns and returns empty string
        tool_response = LLMResponse(
            content="",
            tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
        )
        provider = _make_provider(
            tool_response, tool_response, tool_response, tool_response, tool_response
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors(), max_turns=3)
        result = await loop.run(system_prompt="sys", user_input="keep reading")
        # Loop stopped at max_turns with empty content — partial result
        assert result == ""
        assert provider.generate.call_count <= 3


@pytest.mark.unit
@pytest.mark.req("REQ-25.6")
class TestStatePersistencePerTurn:
    """REQ-25.6 — messages accumulate in loop state per turn."""

    async def test_messages_accumulate_in_storage_per_turn(self) -> None:
        """Each turn adds messages to the loop's message list (available for persistence)."""
        provider = _make_provider(
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}],
            ),
            LLMResponse(
                content="",
                tool_calls=[{"function": {"name": "file_read", "arguments": {"path": "b.txt"}}}],
            ),
            LLMResponse(content="Done reading both.", tool_calls=None),
        )
        loop = AgentLoop(provider=provider, tool_executors=_make_tool_executors())
        await loop.run(system_prompt="sys", user_input="read both files")

        # Messages should contain: system, user, assistant+tool (turn 1),
        # assistant+tool (turn 2), assistant (final)
        assert len(loop.messages) >= 7
        # Each turn's tool result is persisted
        tool_msgs = [m for m in loop.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        # All assistant messages are persisted
        assistant_msgs = [m for m in loop.messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 3


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
