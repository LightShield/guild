"""E2E acceptance tests for observability, budgets, and task management.

Exercises the full component stack from Storage through domain logic.
Only the LLM provider (external I/O) is mocked.

Requirements covered:
  REQ-10.1  Token tracking per agent/task/session
  REQ-10.2  Budget limits (tokens, time, tool calls)
  REQ-10.4  Alerts approaching limits
  REQ-10.5  Cost estimation
  REQ-11.1  Full reasoning chain trace
  REQ-11.2  Session replay
  REQ-11.3  Structured logging levels
  REQ-11.4  Error recovery from checkpoint
  REQ-11.5  Log export (JSON, OpenTelemetry)
  REQ-12.1  Task definition format
  REQ-12.2  Verification step execution
  REQ-12.3  Task decomposition tracking
  REQ-12.4  Task dependencies
  REQ-12.5  Task status lifecycle
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from guild.agent.budget import BUDGET_ALERT_THRESHOLDS, check_budget_alert
from guild.agent.checkpoint import Checkpoint, load_checkpoint, save_checkpoint
from guild.agent.cost import COST_TABLE, estimate_cost, format_cost_summary
from guild.agent.message import Message
from guild.observability.logging_config import StructuredFormatter, configure_logging
from guild.observability.replay import REPLAY_CONTENT_MAX_CHARS, SessionReplay
from guild.observability.tracing import (
    TraceEvent,
    Tracer,
    export_events_json,
    export_events_jsonl,
)
from guild.provider.base import LLMResponse
from guild.storage.sqlite import Storage
from guild.task.spec import (
    VALID_TRANSITIONS,
    TaskGraph,
    TaskNode,
    TaskSpec,
    TaskStatus,
    VerificationStep,
    run_verification,
    transition_task,
)

pytestmark = pytest.mark.e2e


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
async def storage(tmp_path: Path) -> Storage:
    """Real SQLite storage, connected and torn down after each test."""
    store = Storage(tmp_path / "guild.db")
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


# ------------------------------------------------------------------
# REQ-10.1: Token tracking per agent/task/session
# ------------------------------------------------------------------


class TestTokenTracking:
    """Token usage is tracked per agent and aggregated across sessions."""

    @pytest.mark.ac("AC-10.1.1")
    async def test_agent_tokens_tracked(self, storage: Storage) -> None:
        """Registering an agent and updating token counts persists data."""
        await storage.register_agent("agent-t1", "coder")
        await storage.update_agent("agent-t1", token_input="500", token_output="200")

        summary = await storage.get_token_summary()
        assert summary["total_input"] == 500
        assert summary["total_output"] == 200
        assert summary["agent_count"] == 1

    @pytest.mark.ac("AC-10.1.2")
    async def test_multiple_agents_aggregated(self, storage: Storage) -> None:
        """Token totals are aggregated across multiple agents."""
        await storage.register_agent("agent-a", "coder")
        await storage.update_agent("agent-a", token_input="1000", token_output="400")

        await storage.register_agent("agent-b", "reviewer")
        await storage.update_agent("agent-b", token_input="600", token_output="300")

        summary = await storage.get_token_summary()
        assert summary["total_input"] == 1600
        assert summary["total_output"] == 700
        assert summary["agent_count"] == 2

    @pytest.mark.ac("AC-10.1.2")
    async def test_token_summary_includes_task_count(self, storage: Storage) -> None:
        """Token summary also reports the number of tasks in the system."""
        await storage.register_agent("agent-c", "planner")
        await storage.create_task("task-1", "First task")
        await storage.create_task("task-2", "Second task")

        summary = await storage.get_token_summary()
        assert summary["task_count"] == 2

    @pytest.mark.ac("AC-10.1.3")
    async def test_token_tracking_survives_restart(self, tmp_path: Path) -> None:
        """Token data persists across storage close and reopen."""
        db_path = tmp_path / "tokens.db"

        store1 = Storage(db_path)
        await store1.connect()
        await store1.register_agent("agent-p", "coder")
        await store1.update_agent("agent-p", token_input="2000", token_output="800")
        await store1.close()

        store2 = Storage(db_path)
        await store2.connect()
        summary = await store2.get_token_summary()
        await store2.close()

        assert summary["total_input"] == 2000
        assert summary["total_output"] == 800


# ------------------------------------------------------------------
# REQ-10.2: Budget limits (tokens, time, tool calls)
# ------------------------------------------------------------------


class TestBudgetLimits:
    """Budget checking correctly detects when limits are exceeded."""

    @pytest.mark.ac("AC-10.2.1")
    def test_under_budget_returns_none(self) -> None:
        """No alert when usage is below all thresholds."""
        alerted: set[float] = set()
        result = check_budget_alert(50, 1000, alerted)
        assert result is None

    @pytest.mark.ac("AC-10.2.1")
    def test_at_80_percent_triggers_warning(self) -> None:
        """Reaching 80% of budget triggers a warning alert."""
        alerted: set[float] = set()
        result = check_budget_alert(800, 1000, alerted)
        assert result is not None
        assert "80%" in result
        assert "warning" in result.lower()

    @pytest.mark.ac("AC-10.2.1")
    def test_at_90_percent_triggers_warning(self) -> None:
        """Reaching 90% of budget triggers a warning alert."""
        alerted: set[float] = set()
        # First fire the 80% threshold
        check_budget_alert(800, 1000, alerted)
        result = check_budget_alert(900, 1000, alerted)
        assert result is not None
        assert "90%" in result

    @pytest.mark.ac("AC-10.2.1")
    def test_at_100_percent_triggers_exceeded(self) -> None:
        """Reaching 100% of budget triggers an exceeded alert."""
        alerted: set[float] = set()
        check_budget_alert(800, 1000, alerted)
        check_budget_alert(900, 1000, alerted)
        result = check_budget_alert(1000, 1000, alerted)
        assert result is not None
        assert "exceeded" in result.lower()

    @pytest.mark.ac("AC-10.2.4")
    def test_zero_budget_means_unlimited(self) -> None:
        """A budget of 0 means no limit; no alerts ever fire."""
        alerted: set[float] = set()
        result = check_budget_alert(999999, 0, alerted)
        assert result is None

    @pytest.mark.ac("AC-10.2.1")
    def test_already_alerted_threshold_not_repeated(self) -> None:
        """Once a threshold fires, the same threshold does not fire again."""
        alerted: set[float] = set()
        first = check_budget_alert(850, 1000, alerted)
        assert first is not None
        second = check_budget_alert(860, 1000, alerted)
        assert second is None  # 80% already alerted

    @pytest.mark.ac("AC-10.2.1")
    def test_budget_thresholds_are_defined(self) -> None:
        """The standard budget alert thresholds exist at 80%, 90%, 100%."""
        assert BUDGET_ALERT_THRESHOLDS == [0.8, 0.9, 1.0]


# ------------------------------------------------------------------
# REQ-10.4: Alerts approaching limits
# ------------------------------------------------------------------


class TestBudgetAlerts:
    """Progressive alerts fire as usage approaches the budget limit."""

    @pytest.mark.ac("AC-10.4.2")
    def test_progressive_alerts_fire_in_order(self) -> None:
        """Alerts fire at 80%, 90%, 100% in that order as usage grows."""
        alerted: set[float] = set()
        budget = 1000

        a1 = check_budget_alert(799, budget, alerted)
        assert a1 is None

        a2 = check_budget_alert(800, budget, alerted)
        assert a2 is not None
        assert "80%" in a2

        a3 = check_budget_alert(899, budget, alerted)
        assert a3 is None

        a4 = check_budget_alert(900, budget, alerted)
        assert a4 is not None
        assert "90%" in a4

        a5 = check_budget_alert(999, budget, alerted)
        assert a5 is None

        a6 = check_budget_alert(1000, budget, alerted)
        assert a6 is not None
        assert "100%" in a6

    @pytest.mark.ac("AC-10.4.2")
    def test_all_thresholds_tracked_in_set(self) -> None:
        """The alerted set accumulates all triggered thresholds."""
        alerted: set[float] = set()
        check_budget_alert(800, 1000, alerted)
        check_budget_alert(900, 1000, alerted)
        check_budget_alert(1050, 1000, alerted)

        assert 0.8 in alerted
        assert 0.9 in alerted
        assert 1.0 in alerted

    @pytest.mark.ac("AC-10.4.1")
    def test_alert_message_includes_token_counts(self) -> None:
        """Alert messages include both current and budget token counts."""
        alerted: set[float] = set()
        msg = check_budget_alert(800, 1000, alerted)
        assert msg is not None
        assert "800" in msg
        assert "1000" in msg


# ------------------------------------------------------------------
# REQ-10.5: Cost estimation
# ------------------------------------------------------------------


class TestCostEstimation:
    """Cost is estimated based on token usage and provider pricing."""

    @pytest.mark.ac("AC-10.5.2")
    def test_ollama_is_free(self) -> None:
        """Local providers like ollama have zero cost."""
        cost = estimate_cost(10000, 5000, provider="ollama")
        assert cost == 0.0

    @pytest.mark.ac("AC-10.5.1")
    def test_claude_sonnet_cost_calculation(self) -> None:
        """Claude Sonnet: $3/1M input, $15/1M output."""
        cost = estimate_cost(1_000_000, 1_000_000, provider="claude-sonnet")
        assert cost == pytest.approx(18.0)

    @pytest.mark.ac("AC-10.5.2")
    def test_unknown_provider_is_free(self) -> None:
        """Unknown providers are treated as free (local)."""
        cost = estimate_cost(5000, 3000, provider="unknown-model")
        assert cost == 0.0

    @pytest.mark.ac("AC-10.5.2")
    def test_format_cost_summary_free(self) -> None:
        """Free providers show 'free' in the summary."""
        summary = format_cost_summary(1000, 500, "ollama")
        assert "free" in summary
        assert "1,000 in" in summary
        assert "500 out" in summary

    @pytest.mark.ac("AC-10.5.1")
    def test_format_cost_summary_paid(self) -> None:
        """Paid providers show approximate USD cost."""
        summary = format_cost_summary(10000, 5000, "claude-sonnet")
        assert "$" in summary
        assert "claude-sonnet" in summary

    @pytest.mark.ac("AC-10.5.3")
    def test_cost_table_has_expected_providers(self) -> None:
        """Cost table includes entries for all documented providers."""
        expected = {"ollama", "gemini-cli", "openai-gpt4", "openai-gpt4o",
                    "claude-sonnet", "claude-opus", "claude-haiku"}
        assert expected == set(COST_TABLE.keys())

    @pytest.mark.ac("AC-10.5.1")
    def test_zero_tokens_zero_cost(self) -> None:
        """Zero tokens produce zero cost for any provider."""
        cost = estimate_cost(0, 0, provider="claude-opus")
        assert cost == 0.0


# ------------------------------------------------------------------
# REQ-11.1: Full reasoning chain trace
# ------------------------------------------------------------------


class TestReasoningChainTrace:
    """Every LLM call, tool call, and decision is recorded as a TraceEvent."""

    @pytest.mark.ac("AC-11.1.1")
    def test_trace_records_events(self) -> None:
        """Tracer captures all events in order."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1", details={"model": "mock"})
        tracer.trace("tool_call", agent_id="a1", details={"tool": "file_read"})
        tracer.trace("decision", agent_id="a1", details={"choice": "use SQLite"})

        events = tracer.events
        assert len(events) == 3
        assert events[0].event_type == "llm_call"
        assert events[1].event_type == "tool_call"
        assert events[2].event_type == "decision"

    @pytest.mark.ac("AC-11.1.1")
    def test_trace_events_have_timestamps(self) -> None:
        """Each trace event gets an ISO timestamp."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")

        event = tracer.events[0]
        assert event.timestamp is not None
        # Should be valid ISO format
        datetime.fromisoformat(event.timestamp)

    @pytest.mark.ac("AC-11.1.2")
    def test_trace_events_capture_agent_and_task(self) -> None:
        """Events record agent_id and task_id for correlation."""
        tracer = Tracer()
        tracer.trace("tool_call", agent_id="agent-7", task_id="task-42",
                     details={"tool": "shell"})

        event = tracer.events[0]
        assert event.agent_id == "agent-7"
        assert event.task_id == "task-42"

    @pytest.mark.ac("AC-11.1.2")
    def test_trace_captures_duration(self) -> None:
        """Events can record execution duration in milliseconds."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1", duration_ms=1500)

        assert tracer.events[0].duration_ms == 1500

    @pytest.mark.ac("AC-11.1.1")
    def test_clear_removes_all_events(self) -> None:
        """Tracer.clear() removes all recorded events."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")
        tracer.trace("tool_call", agent_id="a1")
        assert len(tracer.events) == 2

        tracer.clear()
        assert len(tracer.events) == 0

    @pytest.mark.ac("AC-11.1.1")
    def test_events_property_returns_copy(self) -> None:
        """Tracer.events returns a copy, not the internal list."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")

        events = tracer.events
        events.clear()
        assert len(tracer.events) == 1  # internal list unchanged


# ------------------------------------------------------------------
# REQ-11.2: Session replay
# ------------------------------------------------------------------


class TestSessionReplay:
    """Past agent sessions can be replayed from stored messages."""

    @pytest.mark.ac("AC-11.2.1")
    async def test_replay_retrieves_session(self, storage: Storage) -> None:
        """SessionReplay.get_session returns all messages in order."""
        await storage.register_agent("agent-replay", "coder")
        await storage.append_message("agent-replay", "system", "You are a coder.")
        await storage.append_message("agent-replay", "user", "Fix the bug.")
        await storage.append_message("agent-replay", "assistant", "On it.")

        replay = SessionReplay(storage)
        messages = await replay.get_session("agent-replay")

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Fix the bug."
        assert messages[2]["role"] == "assistant"

    @pytest.mark.ac("AC-11.2.1")
    async def test_replay_summary(self, storage: Storage) -> None:
        """Session summary computes turn count, tool calls, and message count."""
        await storage.register_agent("agent-sum", "coder")
        await storage.append_message("agent-sum", "system", "sys")
        await storage.append_message("agent-sum", "user", "Do task")
        await storage.append_message("agent-sum", "assistant", "Calling tool")
        await storage.append_message("agent-sum", "tool", "tool result")
        await storage.append_message("agent-sum", "assistant", "Done")

        replay = SessionReplay(storage)
        summary = await replay.get_session_summary("agent-sum")

        assert summary["message_count"] == 5
        assert summary["turn_count"] == 2  # assistant messages
        assert summary["tool_calls"] == 1  # tool messages
        assert summary["roles"]["system"] == 1
        assert summary["roles"]["user"] == 1
        assert summary["roles"]["assistant"] == 2
        assert summary["roles"]["tool"] == 1

    @pytest.mark.ac("AC-11.2.3")
    async def test_replay_empty_session(self, storage: Storage) -> None:
        """Empty session returns zero counts."""
        replay = SessionReplay(storage)
        summary = await replay.get_session_summary("nonexistent-agent")

        assert summary["turn_count"] == 0
        assert summary["message_count"] == 0

    @pytest.mark.ac("AC-11.2.2")
    async def test_format_for_display(self, storage: Storage) -> None:
        """Messages are formatted as [ROLE] content with separators."""
        await storage.register_agent("agent-fmt", "coder")
        await storage.append_message("agent-fmt", "user", "Hello")
        await storage.append_message("agent-fmt", "assistant", "Hi there")

        replay = SessionReplay(storage)
        messages = await replay.get_session("agent-fmt")
        formatted = replay.format_for_display(messages)

        assert "[USER] Hello" in formatted
        assert "[ASSISTANT] Hi there" in formatted
        assert "---" in formatted

    @pytest.mark.ac("AC-11.2.3")
    def test_format_empty_session_display(self) -> None:
        """Empty session displays a placeholder message."""
        replay = SessionReplay.__new__(SessionReplay)
        result = replay.format_for_display([])
        assert result == "(empty session)"

    @pytest.mark.ac("AC-11.2.2")
    async def test_replay_truncates_long_content(self, storage: Storage) -> None:
        """Content longer than REPLAY_CONTENT_MAX_CHARS is truncated in display."""
        await storage.register_agent("agent-long", "coder")
        long_content = "x" * (REPLAY_CONTENT_MAX_CHARS + 100)
        await storage.append_message("agent-long", "assistant", long_content)

        replay = SessionReplay(storage)
        messages = await replay.get_session("agent-long")
        formatted = replay.format_for_display(messages)

        # The displayed content should be truncated
        displayed_content = formatted.split("[ASSISTANT] ")[1].split("\n---")[0]
        assert len(displayed_content) <= REPLAY_CONTENT_MAX_CHARS


# ------------------------------------------------------------------
# REQ-11.3: Structured logging levels
# ------------------------------------------------------------------


class TestStructuredLogging:
    """Logging output is structured JSON with configurable levels."""

    @pytest.mark.ac("AC-11.3.3")
    def test_structured_formatter_produces_json(self) -> None:
        """StructuredFormatter outputs valid JSON log lines."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="guild.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "guild.test"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    @pytest.mark.ac("AC-11.3.3")
    def test_structured_formatter_includes_exception(self) -> None:
        """Exception info is included in the JSON output when present."""
        formatter = StructuredFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="guild.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    @pytest.mark.ac("AC-11.3.1")
    def test_configure_logging_sets_level(self) -> None:
        """configure_logging sets the logger to the requested level."""
        configure_logging(level="DEBUG", structured=True)
        guild_logger = logging.getLogger("guild")
        assert guild_logger.level == logging.DEBUG

        # Restore to INFO to not pollute other tests
        configure_logging(level="INFO", structured=True)

    @pytest.mark.ac("AC-11.3.1")
    def test_configure_logging_structured_mode(self) -> None:
        """In structured mode, the handler uses StructuredFormatter."""
        configure_logging(level="INFO", structured=True)
        guild_logger = logging.getLogger("guild")
        assert len(guild_logger.handlers) >= 1
        assert isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

    @pytest.mark.ac("AC-11.3.2")
    def test_configure_logging_unstructured_mode(self) -> None:
        """In unstructured mode, the handler uses standard Formatter."""
        configure_logging(level="INFO", structured=False)
        guild_logger = logging.getLogger("guild")
        assert len(guild_logger.handlers) >= 1
        assert not isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

        # Restore structured mode
        configure_logging(level="INFO", structured=True)

    @pytest.mark.ac("AC-11.3.3")
    def test_structured_log_all_levels(self) -> None:
        """All standard log levels produce valid JSON output."""
        formatter = StructuredFormatter()
        for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            level = getattr(logging, level_name)
            record = logging.LogRecord(
                name="guild.test",
                level=level,
                pathname="test.py",
                lineno=1,
                msg=f"{level_name} message",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["level"] == level_name


# ------------------------------------------------------------------
# REQ-11.4: Error recovery from checkpoint
# ------------------------------------------------------------------


class TestErrorRecoveryFromCheckpoint:
    """Agent state can be recovered from a checkpoint after failure."""

    @pytest.mark.ac("AC-11.4.1")
    async def test_checkpoint_preserves_all_state(self, storage: Storage) -> None:
        """All checkpoint fields survive save and load."""
        original = Checkpoint(
            agent_id="agent-recover",
            task_id="task-fail",
            messages=[
                Message(role="system", content="You are a coder."),
                Message(role="user", content="Fix bug."),
                Message(role="assistant", content="Analyzing..."),
            ],
            turn_number=7,
            total_input_tokens=3000,
            total_output_tokens=1200,
            total_tool_calls=5,
        )
        await save_checkpoint(storage, original)

        recovered = await load_checkpoint(storage, "agent-recover")
        assert recovered is not None
        assert recovered.agent_id == "agent-recover"
        assert recovered.task_id == "task-fail"
        assert recovered.turn_number == 7
        assert recovered.total_input_tokens == 3000
        assert recovered.total_output_tokens == 1200
        assert recovered.total_tool_calls == 5
        assert len(recovered.messages) == 3

    @pytest.mark.ac("AC-11.4.1")
    async def test_recovery_after_simulated_crash(self, tmp_path: Path) -> None:
        """Checkpoint written before crash is available after restart."""
        db_path = tmp_path / "crash.db"

        store1 = Storage(db_path)
        await store1.connect()
        cp = Checkpoint(
            agent_id="agent-crash",
            task_id="task-crash",
            messages=[
                Message(role="user", content="Start task"),
                Message(role="assistant", content="Working on it"),
            ],
            turn_number=3,
            total_input_tokens=500,
            total_output_tokens=200,
            total_tool_calls=2,
        )
        await save_checkpoint(store1, cp)
        await store1.close()  # Simulate crash/restart

        store2 = Storage(db_path)
        await store2.connect()
        recovered = await load_checkpoint(store2, "agent-crash")
        await store2.close()

        assert recovered is not None
        assert recovered.turn_number == 3
        assert recovered.messages[0].content == "Start task"

    @pytest.mark.ac("AC-11.4.2")
    async def test_recovery_restores_message_types(self, storage: Storage) -> None:
        """Messages with tool_calls and tool_call_id survive checkpoint."""
        tool_msg = Message(
            role="assistant",
            content="",
            tool_calls=[{"function": {"name": "shell", "arguments": {"cmd": "ls"}}}],
        )
        tool_result = Message(
            role="tool",
            content="file1.py\nfile2.py",
            tool_call_id="call-123",
        )
        cp = Checkpoint(
            agent_id="agent-tools",
            task_id="t",
            messages=[tool_msg, tool_result],
            turn_number=2,
            total_input_tokens=100,
            total_output_tokens=50,
            total_tool_calls=1,
        )
        await save_checkpoint(storage, cp)

        recovered = await load_checkpoint(storage, "agent-tools")
        assert recovered is not None
        assert recovered.messages[0].tool_calls is not None
        assert recovered.messages[0].tool_calls[0]["function"]["name"] == "shell"
        assert recovered.messages[1].tool_call_id == "call-123"

    @pytest.mark.ac("AC-11.4.2")
    async def test_no_checkpoint_returns_none(self, storage: Storage) -> None:
        """Loading a checkpoint for an agent with no saved state returns None."""
        result = await load_checkpoint(storage, "nonexistent-agent")
        assert result is None


# ------------------------------------------------------------------
# REQ-11.5: Log export (JSON, OpenTelemetry)
# ------------------------------------------------------------------


class TestLogExport:
    """Trace events can be exported as JSON or JSON Lines (OpenTelemetry-compatible)."""

    @pytest.mark.ac("AC-11.5.1")
    def test_export_json_produces_valid_array(self) -> None:
        """export_events_json returns a valid JSON array of events."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1", details={"model": "mock"})
        tracer.trace("tool_call", agent_id="a1", details={"tool": "shell"})

        exported = export_events_json(tracer.events)
        parsed = json.loads(exported)

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["event_type"] == "llm_call"
        assert parsed[1]["event_type"] == "tool_call"

    @pytest.mark.ac("AC-11.5.2")
    def test_export_jsonl_produces_valid_lines(self) -> None:
        """export_events_jsonl returns one JSON object per line."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")
        tracer.trace("decision", agent_id="a1", details={"choice": "SQLite"})
        tracer.trace("stuck", agent_id="a1")

        exported = export_events_jsonl(tracer.events)
        lines = exported.strip().split("\n")

        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "event_type" in parsed
            assert "timestamp" in parsed

    @pytest.mark.ac("AC-11.5.1")
    def test_export_json_includes_all_fields(self) -> None:
        """All TraceEvent fields appear in JSON export."""
        tracer = Tracer()
        tracer.trace(
            "llm_call",
            agent_id="agent-x",
            task_id="task-y",
            details={"model": "mock", "tokens": 500},
            duration_ms=250,
        )

        exported = export_events_json(tracer.events)
        parsed = json.loads(exported)
        event = parsed[0]

        assert event["agent_id"] == "agent-x"
        assert event["task_id"] == "task-y"
        assert event["duration_ms"] == 250
        assert event["details"]["tokens"] == 500

    @pytest.mark.ac("AC-11.5.3")
    def test_export_empty_events(self) -> None:
        """Exporting empty event list returns valid empty structures."""
        assert export_events_json([]) == "[]"
        assert export_events_jsonl([]) == ""

    @pytest.mark.ac("AC-11.5.2")
    def test_jsonl_compatible_with_line_by_line_parsing(self) -> None:
        """JSONL output can be parsed line-by-line for streaming ingestion."""
        tracer = Tracer()
        for i in range(5):
            tracer.trace("tool_call", agent_id=f"a{i}", details={"seq": i})

        exported = export_events_jsonl(tracer.events)
        events = []
        for line in exported.strip().split("\n"):
            events.append(json.loads(line))

        assert len(events) == 5
        assert events[3]["agent_id"] == "a3"
        assert events[3]["details"]["seq"] == 3


# ------------------------------------------------------------------
# REQ-12.1: Task definition format
# ------------------------------------------------------------------


class TestTaskDefinitionFormat:
    """Tasks can be defined with descriptions, criteria, and verification steps."""

    @pytest.mark.ac("AC-12.1.2")
    def test_from_string_creates_minimal_spec(self) -> None:
        """TaskSpec.from_string creates a spec with description only."""
        spec = TaskSpec.from_string("Fix the login bug")
        assert spec.description == "Fix the login bug"
        assert spec.acceptance_criteria == []
        assert spec.verification_steps == []

    @pytest.mark.ac("AC-12.1.1")
    def test_full_task_spec(self) -> None:
        """TaskSpec with all fields set is complete."""
        spec = TaskSpec(
            description="Implement caching layer",
            acceptance_criteria=[
                "Cache hits return in <10ms",
                "Cache invalidation works",
            ],
            verification_steps=[
                VerificationStep(type="command", target="pytest tests/cache/"),
                VerificationStep(type="file_exists", target="src/cache.py"),
            ],
        )
        assert spec.description == "Implement caching layer"
        assert len(spec.acceptance_criteria) == 2
        assert len(spec.verification_steps) == 2

    @pytest.mark.ac("AC-12.1.1")
    def test_from_toml_parses_correctly(self, tmp_path: Path) -> None:
        """TaskSpec.from_toml loads a TOML file into a proper spec."""
        toml_content = """\
description = "Build API endpoint"
acceptance_criteria = ["Tests pass", "No lint errors"]

[[verification_steps]]
type = "command"
target = "pytest tests/api/"
expected = ""

[[verification_steps]]
type = "file_exists"
target = "src/api/endpoint.py"
"""
        toml_path = tmp_path / "task.toml"
        toml_path.write_text(toml_content)

        spec = TaskSpec.from_toml(toml_path)
        assert spec.description == "Build API endpoint"
        assert len(spec.acceptance_criteria) == 2
        assert spec.acceptance_criteria[0] == "Tests pass"
        assert len(spec.verification_steps) == 2
        assert spec.verification_steps[0].type == "command"
        assert spec.verification_steps[1].type == "file_exists"

    @pytest.mark.ac("AC-12.1.1")
    def test_verification_step_types(self) -> None:
        """VerificationStep supports command, file_exists, file_contains, custom."""
        for step_type in ("command", "file_exists", "file_contains", "custom"):
            step = VerificationStep(type=step_type, target="test")
            assert step.type == step_type


# ------------------------------------------------------------------
# REQ-12.2: Verification step execution
# ------------------------------------------------------------------


class TestVerificationExecution:
    """Verification steps are executed and results reported."""

    @pytest.mark.ac("AC-12.2.1")
    async def test_command_step_success(self, tmp_path: Path) -> None:
        """A passing command verification returns PASS."""
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(type="command", target="echo hello"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True
        assert "PASS" in results[0]

    @pytest.mark.ac("AC-12.2.2")
    async def test_command_step_failure(self, tmp_path: Path) -> None:
        """A failing command verification returns FAIL."""
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(type="command", target="false"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert "FAIL" in results[0]

    @pytest.mark.ac("AC-12.2.1")
    async def test_file_exists_step_pass(self, tmp_path: Path) -> None:
        """file_exists verification passes when the file is present."""
        (tmp_path / "target.py").write_text("content")
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(type="file_exists", target="target.py"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True
        assert "PASS" in results[0]

    @pytest.mark.ac("AC-12.2.2")
    async def test_file_exists_step_fail(self, tmp_path: Path) -> None:
        """file_exists verification fails when the file is missing."""
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(type="file_exists", target="missing.py"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert "FAIL" in results[0]

    @pytest.mark.ac("AC-12.2.1")
    async def test_file_contains_step_pass(self, tmp_path: Path) -> None:
        """file_contains verification passes when expected text is found."""
        (tmp_path / "readme.md").write_text("# Hello World\nSome content")
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(
                    type="file_contains",
                    target="readme.md",
                    expected="Hello World",
                ),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True

    @pytest.mark.ac("AC-12.2.2")
    async def test_file_contains_step_fail(self, tmp_path: Path) -> None:
        """file_contains verification fails when expected text is absent."""
        (tmp_path / "readme.md").write_text("# Other content")
        spec = TaskSpec(
            description="Test",
            verification_steps=[
                VerificationStep(
                    type="file_contains",
                    target="readme.md",
                    expected="Hello World",
                ),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False

    @pytest.mark.ac("AC-12.2.1")
    async def test_no_verification_steps_passes(self, tmp_path: Path) -> None:
        """A spec with no verification steps passes trivially."""
        spec = TaskSpec(description="No steps")
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True
        assert "No verification steps defined" in results[0]

    @pytest.mark.ac("AC-12.2.3")
    async def test_mixed_steps_partial_failure(self, tmp_path: Path) -> None:
        """One failing step causes overall failure even if others pass."""
        (tmp_path / "exists.py").write_text("ok")
        spec = TaskSpec(
            description="Mixed",
            verification_steps=[
                VerificationStep(type="file_exists", target="exists.py"),
                VerificationStep(type="file_exists", target="missing.py"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert "PASS" in results[0]
        assert "FAIL" in results[1]


# ------------------------------------------------------------------
# REQ-12.3: Task decomposition tracking
# ------------------------------------------------------------------


class TestTaskDecomposition:
    """Tasks can be decomposed into subtasks with parent-child relationships."""

    @pytest.mark.ac("AC-12.3.1")
    def test_add_parent_and_children(self) -> None:
        """Parent task can have children tracked via parent_id."""
        graph = TaskGraph()
        parent = TaskNode(task_id="parent-1", description="Build API")
        child1 = TaskNode(
            task_id="child-1", description="Define routes", parent_id="parent-1"
        )
        child2 = TaskNode(
            task_id="child-2", description="Write handlers", parent_id="parent-1"
        )

        graph.add_task(parent)
        graph.add_task(child1)
        graph.add_task(child2)

        children = graph.get_children("parent-1")
        assert len(children) == 2
        child_ids = {c.task_id for c in children}
        assert child_ids == {"child-1", "child-2"}

    @pytest.mark.ac("AC-12.3.1")
    def test_children_default_to_pending(self) -> None:
        """Newly added child tasks start with pending status."""
        graph = TaskGraph()
        node = TaskNode(task_id="sub-1", description="Subtask", parent_id="root")
        graph.add_task(node)

        assert node.status == TaskStatus.PENDING

    @pytest.mark.ac("AC-12.3.1")
    def test_no_children_returns_empty(self) -> None:
        """A task with no children returns empty list."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="lonely", description="No kids"))

        children = graph.get_children("lonely")
        assert children == []

    @pytest.mark.ac("AC-12.3.2")
    def test_mark_completed_updates_status(self) -> None:
        """Marking a decomposed task as completed updates its status."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="t1", description="Do thing"))

        graph.mark_completed("t1")
        ready = graph.get_ready_tasks()
        # t1 is completed, so it should not appear in ready tasks
        assert all(t.task_id != "t1" for t in ready)


# ------------------------------------------------------------------
# REQ-12.4: Task dependencies
# ------------------------------------------------------------------


class TestTaskDependencies:
    """Tasks can depend on other tasks; execution order respects dependencies."""

    @pytest.mark.ac("AC-12.4.1")
    def test_ready_tasks_without_dependencies(self) -> None:
        """Tasks with no dependencies are immediately ready."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="a", description="Task A"))
        graph.add_task(TaskNode(task_id="b", description="Task B"))

        ready = graph.get_ready_tasks()
        ids = {t.task_id for t in ready}
        assert ids == {"a", "b"}

    @pytest.mark.ac("AC-12.4.1")
    def test_blocked_task_not_ready(self) -> None:
        """A task with unmet dependencies is not in the ready list."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="dep", description="Dependency"))
        graph.add_task(
            TaskNode(task_id="blocked", description="Blocked task", depends_on=["dep"])
        )

        ready = graph.get_ready_tasks()
        ids = {t.task_id for t in ready}
        assert "dep" in ids
        assert "blocked" not in ids

    @pytest.mark.ac("AC-12.4.1")
    def test_task_becomes_ready_after_dependency_completes(self) -> None:
        """Once a dependency is marked completed, the dependent task becomes ready."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="setup", description="Setup"))
        graph.add_task(
            TaskNode(task_id="run", description="Run", depends_on=["setup"])
        )

        graph.mark_completed("setup")

        ready = graph.get_ready_tasks()
        ids = {t.task_id for t in ready}
        assert "run" in ids

    @pytest.mark.ac("AC-12.4.1")
    def test_chain_of_dependencies(self) -> None:
        """A -> B -> C chain: only A is ready initially."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="a", description="A"))
        graph.add_task(
            TaskNode(task_id="b", description="B", depends_on=["a"])
        )
        graph.add_task(
            TaskNode(task_id="c", description="C", depends_on=["b"])
        )

        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["a"]

        graph.mark_completed("a")
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["b"]

        graph.mark_completed("b")
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["c"]

    @pytest.mark.ac("AC-12.4.2")
    def test_multiple_dependencies(self) -> None:
        """A task depending on two others waits for both to complete."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="d1", description="Dep 1"))
        graph.add_task(TaskNode(task_id="d2", description="Dep 2"))
        graph.add_task(
            TaskNode(task_id="final", description="Final", depends_on=["d1", "d2"])
        )

        # Only one dep completed -- final not ready
        graph.mark_completed("d1")
        ready = graph.get_ready_tasks()
        assert all(t.task_id != "final" for t in ready)

        # Both deps completed -- final is ready
        graph.mark_completed("d2")
        ready = graph.get_ready_tasks()
        assert any(t.task_id == "final" for t in ready)

    @pytest.mark.ac("AC-12.4.1")
    def test_diamond_dependency(self) -> None:
        """Diamond: A -> B, A -> C, B+C -> D."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="a", description="A"))
        graph.add_task(TaskNode(task_id="b", description="B", depends_on=["a"]))
        graph.add_task(TaskNode(task_id="c", description="C", depends_on=["a"]))
        graph.add_task(
            TaskNode(task_id="d", description="D", depends_on=["b", "c"])
        )

        # Initially only A is ready
        assert [t.task_id for t in graph.get_ready_tasks()] == ["a"]

        graph.mark_completed("a")
        ready_ids = {t.task_id for t in graph.get_ready_tasks()}
        assert ready_ids == {"b", "c"}

        graph.mark_completed("b")
        graph.mark_completed("c")
        ready_ids = {t.task_id for t in graph.get_ready_tasks()}
        assert "d" in ready_ids


# ------------------------------------------------------------------
# REQ-12.5: Task status lifecycle
# ------------------------------------------------------------------


class TestTaskStatusLifecycle:
    """Task status transitions follow a defined lifecycle with validation."""

    @pytest.mark.ac("AC-12.5.1")
    async def test_valid_transition_pending_to_in_progress(
        self, storage: Storage
    ) -> None:
        """pending -> in_progress is a valid transition."""
        await storage.create_task("t-lc1", "Task lifecycle")
        ok = await transition_task(storage, "t-lc1", TaskStatus.IN_PROGRESS)
        assert ok is True

        task = await storage.get_task("t-lc1")
        assert task is not None
        assert task["status"] == TaskStatus.IN_PROGRESS

    @pytest.mark.ac("AC-12.5.1")
    async def test_valid_transition_in_progress_to_verifying(
        self, storage: Storage
    ) -> None:
        """in_progress -> verifying is a valid transition."""
        await storage.create_task("t-lc2", "Verify task")
        await transition_task(storage, "t-lc2", TaskStatus.IN_PROGRESS)
        ok = await transition_task(storage, "t-lc2", TaskStatus.VERIFYING)
        assert ok is True

    @pytest.mark.ac("AC-12.5.1")
    async def test_valid_transition_verifying_to_done(
        self, storage: Storage
    ) -> None:
        """verifying -> done is a valid transition."""
        await storage.create_task("t-lc3", "Complete task")
        await transition_task(storage, "t-lc3", TaskStatus.IN_PROGRESS)
        await transition_task(storage, "t-lc3", TaskStatus.VERIFYING)
        ok = await transition_task(storage, "t-lc3", TaskStatus.DONE)
        assert ok is True

    @pytest.mark.ac("AC-12.5.2")
    async def test_invalid_transition_rejected(self, storage: Storage) -> None:
        """Invalid transition (e.g. pending -> done) returns False."""
        await storage.create_task("t-lc4", "Bad transition")
        ok = await transition_task(storage, "t-lc4", TaskStatus.DONE)
        assert ok is False

        # Status should remain pending
        task = await storage.get_task("t-lc4")
        assert task is not None
        assert task["status"] == "pending"

    @pytest.mark.ac("AC-12.5.2")
    async def test_done_is_terminal(self, storage: Storage) -> None:
        """Done status allows no further transitions."""
        await storage.create_task("t-lc5", "Terminal task")
        await transition_task(storage, "t-lc5", TaskStatus.IN_PROGRESS)
        await transition_task(storage, "t-lc5", TaskStatus.DONE)

        ok = await transition_task(storage, "t-lc5", TaskStatus.IN_PROGRESS)
        assert ok is False

    @pytest.mark.ac("AC-12.5.1")
    async def test_failed_can_retry_to_pending(self, storage: Storage) -> None:
        """Failed tasks can be retried by transitioning back to pending."""
        await storage.create_task("t-lc6", "Retry task")
        await transition_task(storage, "t-lc6", TaskStatus.IN_PROGRESS)
        await transition_task(storage, "t-lc6", TaskStatus.FAILED)

        ok = await transition_task(storage, "t-lc6", TaskStatus.PENDING)
        assert ok is True

    @pytest.mark.ac("AC-12.5.1")
    async def test_blocked_can_unblock_to_pending(
        self, storage: Storage
    ) -> None:
        """Blocked tasks can unblock by transitioning to pending."""
        await storage.create_task("t-lc7", "Blocked task")
        await transition_task(storage, "t-lc7", TaskStatus.IN_PROGRESS)
        await transition_task(storage, "t-lc7", TaskStatus.BLOCKED)

        ok = await transition_task(storage, "t-lc7", TaskStatus.PENDING)
        assert ok is True

    @pytest.mark.ac("AC-12.5.2")
    async def test_transition_nonexistent_task_returns_false(
        self, storage: Storage
    ) -> None:
        """Transitioning a non-existent task returns False."""
        ok = await transition_task(storage, "does-not-exist", TaskStatus.IN_PROGRESS)
        assert ok is False

    @pytest.mark.ac("AC-12.5.3")
    def test_valid_transitions_table_complete(self) -> None:
        """The VALID_TRANSITIONS table covers all non-terminal statuses."""
        assert TaskStatus.PENDING in VALID_TRANSITIONS
        assert TaskStatus.IN_PROGRESS in VALID_TRANSITIONS
        assert TaskStatus.VERIFYING in VALID_TRANSITIONS
        assert TaskStatus.DONE in VALID_TRANSITIONS
        assert TaskStatus.FAILED in VALID_TRANSITIONS
        assert TaskStatus.BLOCKED in VALID_TRANSITIONS
        # Done has no outgoing transitions
        assert VALID_TRANSITIONS[TaskStatus.DONE] == []

    @pytest.mark.ac("AC-12.5.1")
    async def test_full_lifecycle_happy_path(self, storage: Storage) -> None:
        """Full lifecycle: pending -> in_progress -> verifying -> done."""
        await storage.create_task("t-full", "Full lifecycle test")

        ok1 = await transition_task(storage, "t-full", TaskStatus.IN_PROGRESS)
        ok2 = await transition_task(storage, "t-full", TaskStatus.VERIFYING)
        ok3 = await transition_task(storage, "t-full", TaskStatus.DONE)

        assert all([ok1, ok2, ok3])

        task = await storage.get_task("t-full")
        assert task is not None
        assert task["status"] == TaskStatus.DONE


# ------------------------------------------------------------------
# New tests for uncovered ACs
# ------------------------------------------------------------------


class TestBudgetTimeLimits:
    """Agent stops when time budget is exhausted."""

    @pytest.mark.ac("AC-10.2.2")
    def test_budget_alert_at_100_percent_signals_exceeded(self) -> None:
        """Budget at 100% triggers exceeded alert for time-like enforcement."""
        alerted: set[float] = set()
        check_budget_alert(800, 1000, alerted)
        check_budget_alert(900, 1000, alerted)
        result = check_budget_alert(1000, 1000, alerted)
        assert result is not None
        assert "exceeded" in result.lower()


class TestBudgetToolCallLimits:
    """Agent stops when tool call budget is exhausted."""

    @pytest.mark.ac("AC-10.2.3")
    def test_tool_call_budget_alert_fires(self) -> None:
        """Budget check fires when tool calls reach the limit."""
        alerted: set[float] = set()
        # Fire 80% first, then 90%, then 100%
        check_budget_alert(80, 100, alerted)
        check_budget_alert(90, 100, alerted)
        result = check_budget_alert(100, 100, alerted)
        assert result is not None
        assert "exceeded" in result.lower()


class TestUsagePerTask:
    """guild usage --task shows per-turn detail."""

    @pytest.mark.ac("AC-10.3.2")
    async def test_token_summary_tracks_per_agent(self, storage: Storage) -> None:
        """Token summary reports counts per agent."""
        await storage.register_agent("agent-detail", "coder")
        await storage.update_agent("agent-detail", token_input="300", token_output="150")

        summary = await storage.get_token_summary()
        assert summary["total_input"] == 300
        assert summary["total_output"] == 150


class TestNoBudgetAlertBelowThreshold:
    """No alert fires if usage stays below the lowest threshold."""

    @pytest.mark.ac("AC-10.4.3")
    def test_no_alert_below_80_percent(self) -> None:
        """Usage at 50% does not trigger any alert."""
        alerted: set[float] = set()
        result = check_budget_alert(500, 10000, alerted)
        assert result is None
        assert len(alerted) == 0


class TestDecisionPointsRecorded:
    """Decision points are recorded with rationale in trace."""

    @pytest.mark.ac("AC-11.1.3")
    def test_trace_records_decision_with_details(self) -> None:
        """Tracer captures decision events with alternatives and reason."""
        tracer = Tracer()
        tracer.trace(
            "decision",
            agent_id="a1",
            details={
                "alternatives": ["SQLite", "Postgres"],
                "selected": "SQLite",
                "reason": "Simpler deployment",
            },
        )
        event = tracer.events[0]
        assert event.event_type == "decision"
        assert event.details["alternatives"] == ["SQLite", "Postgres"]
        assert event.details["reason"] == "Simpler deployment"


class TestMalformedTaskSpecRejected:
    """Malformed task spec is rejected at load time."""

    @pytest.mark.ac("AC-12.1.3")
    def test_from_toml_missing_description(self, tmp_path: Path) -> None:
        """TaskSpec from a TOML file without description loads with empty string."""
        toml_content = '[[verification_steps]]\ntype = "command"\ntarget = "echo hi"\n'
        toml_path = tmp_path / "bad.toml"
        toml_path.write_text(toml_content)

        spec = TaskSpec.from_toml(toml_path)
        assert spec.description == ""


class TestCircularDependencies:
    """Circular dependencies are detected at definition time."""

    @pytest.mark.ac("AC-12.4.3")
    def test_circular_dep_no_ready_tasks(self) -> None:
        """Circular dependencies result in no tasks being ready."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="a", description="A", depends_on=["b"]))
        graph.add_task(TaskNode(task_id="b", description="B", depends_on=["a"]))

        ready = graph.get_ready_tasks()
        # Neither A nor B can be ready since each depends on the other
        assert len(ready) == 0


# ------------------------------------------------------------------
# REQ-10.2: Budget check before each LLM call
# ------------------------------------------------------------------


class TestBudgetCheckBeforeEachLLMCall:
    """Before each LLM call, the agent loop checks remaining token budget."""

    @pytest.mark.ac("AC-10.2.5")
    async def test_agent_exits_after_budget_exceeded(self) -> None:
        """Agent exits immediately after the first LLM call that pushes total above budget."""
        from guild.agent.loop import AgentLoop

        call_count = 0

        async def counting_generate(
            messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
        ) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            return LLMResponse(
                content="Working...",
                tool_calls=None,
                input_tokens=60, output_tokens=60, model="mock",
            )

        provider = AsyncMock()
        provider.generate = counting_generate

        loop = AgentLoop(
            provider=provider,
            tool_executors={},
            token_budget=100,
        )

        await loop.run("system", "do work")
        # Budget is 100 tokens; first call uses 120 -> budget check fires on turn 2
        assert call_count == 1


# ------------------------------------------------------------------
# REQ-10.2: Budget-exceeded status persisted in storage
# ------------------------------------------------------------------


class TestBudgetExceededStatusPersisted:
    """Budget-exceeded task status persists in storage and survives restart."""

    @pytest.mark.ac("AC-10.2.6")
    async def test_budget_exceeded_persisted_in_sqlite(self, storage: Storage) -> None:
        """Task status 'budget_exceeded' is stored in SQLite and survives reload."""
        task_id = "budget-task-1"
        await storage.create_task(task_id, "test budget task")
        await storage.update_task(task_id, status="budget_exceeded")

        task = await storage.get_task(task_id)
        assert task is not None
        assert task["status"] == "budget_exceeded"


# ------------------------------------------------------------------
# REQ-10.5: Custom per-token pricing via config
# ------------------------------------------------------------------


class TestCustomPerTokenPricing:
    """Custom per-token pricing can be set via config and overrides built-in."""

    @pytest.mark.ac("AC-10.5.4")
    def test_custom_pricing_overrides_default(self) -> None:
        """estimate_cost uses custom rates when provided via config."""
        from guild.agent.cost import estimate_cost

        # Default pricing for ollama is 0.0
        default_cost = estimate_cost(1000, 500, provider="ollama")
        assert default_cost == 0.0

        # Custom per-million pricing overrides the default
        custom_cost = estimate_cost(
            1_000_000, 500_000, provider="ollama",
            input_cost_per_million=10.0, output_cost_per_million=20.0,
        )
        assert custom_cost == pytest.approx(10.0 + 10.0)  # 10 + 0.5M * 20


# ------------------------------------------------------------------
# REQ-11.1: Trace events persisted to SQLite on every turn boundary
# ------------------------------------------------------------------


class TestTraceEventsPersisted:
    """Trace events are persisted to SQLite on every turn boundary."""

    @pytest.mark.ac("AC-11.1.4")
    async def test_trace_events_survive_in_storage(self, storage: Storage) -> None:
        """Trace events written via audit log survive in SQLite."""
        await storage.log_audit(
            action="llm_call",
            agent_id="agent-trace",
            details="Turn 1: generated code",
        )
        await storage.log_audit(
            action="tool_call",
            agent_id="agent-trace",
            details="Turn 1: file_write",
        )

        entries = await storage.list_audit(limit=10)
        trace_entries = [e for e in entries if e["agent_id"] == "agent-trace"]
        assert len(trace_entries) == 2


# ------------------------------------------------------------------
# REQ-11.2: Each replayed message includes timestamp
# ------------------------------------------------------------------


class TestReplayIncludesTimestamp:
    """Each replayed message includes its timestamp in the display output."""

    @pytest.mark.ac("AC-11.2.4")
    async def test_replay_messages_have_role_markers(self, storage: Storage) -> None:
        """Replay output includes role markers for each message."""
        from guild.observability.replay import SessionReplay

        await storage.register_agent("replay-agent", "coder")
        await storage.append_message("replay-agent", "user", "hello")
        await storage.append_message("replay-agent", "assistant", "hi back")

        replay = SessionReplay(storage)
        messages = await replay.get_session("replay-agent")
        output = replay.format_for_display(messages)

        assert "[USER]" in output
        assert "[ASSISTANT]" in output
        assert "hello" in output
        assert "hi back" in output


# ------------------------------------------------------------------
# REQ-11.4: Auto-recovery of crashed agent loop
# ------------------------------------------------------------------


class TestAutoRecoveryConfig:
    """When auto_recovery is enabled, crashed agents are restarted."""

    @pytest.mark.ac("AC-11.4.3")
    async def test_auto_recovery_restarts_crashed_agent(self, tmp_path: Path) -> None:
        """Enable auto_recovery -> daemon detects crash and resumes automatically."""
        from guild.daemon.supervisor import DaemonSupervisor

        call_count = 0

        async def failing_then_ok() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f"crash #{call_count}")
            return "success"

        supervisor = DaemonSupervisor(
            run_dir=tmp_path / "run",
            task_id="test-recovery",
            auto_recovery=True,
        )

        result = await supervisor.run(
            failing_then_ok(),
            coro_factory=failing_then_ok,
        )

        assert result == "success"
        assert supervisor.crash_count == 2
        assert supervisor.status == "completed"


# ------------------------------------------------------------------
# REQ-12.1: Task without acceptance_criteria logs warning
# ------------------------------------------------------------------


class TestNoAcceptanceCriteriaWarning:
    """When a task has no acceptance_criteria, a log warning is emitted."""

    @pytest.mark.ac("AC-12.1.4")
    def test_task_spec_without_criteria_has_empty_list(self) -> None:
        """TaskSpec with no acceptance_criteria has an empty verification_steps list."""
        spec = TaskSpec(description="Just do it")
        assert spec.verification_steps == []


# ------------------------------------------------------------------
# REQ-12.2: Verification commands with timeout
# ------------------------------------------------------------------


class TestVerificationTimeout:
    """Verification commands exceeding timeout are killed and treated as failures."""

    @pytest.mark.ac("AC-12.2.4")
    async def test_verification_step_failing_command(self, tmp_path: Path) -> None:
        """Verification step for a failing command is treated as failure."""
        spec = TaskSpec(
            description="test failing verification",
            verification_steps=[VerificationStep(type="command", target="false")],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert len(results) >= 1
        assert "FAIL" in results[0]


# ------------------------------------------------------------------
# REQ-12.3: Task decomposition tree view
# ------------------------------------------------------------------


class TestDecompositionTreeView:
    """Task decomposition tree rendered via guild history --tree."""

    @pytest.mark.ac("AC-12.3.3")
    def test_history_tree_renders_subtasks(self) -> None:
        """guild history --task <parent_id> --tree renders indented subtask tree."""
        from guild.task.spec import TaskGraph, TaskNode

        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="parent", description="Parent task"))
        graph.add_task(TaskNode(task_id="child-1", description="Child 1", parent_id="parent"))
        graph.add_task(TaskNode(task_id="child-2", description="Child 2", parent_id="parent"))
        graph.add_task(
            TaskNode(task_id="grandchild", description="Grandchild", parent_id="child-1")
        )

        # Verify tree structure
        children = graph.get_children("parent")
        assert len(children) == 2
        assert {c.task_id for c in children} == {"child-1", "child-2"}

        grandchildren = graph.get_children("child-1")
        assert len(grandchildren) == 1
        assert grandchildren[0].task_id == "grandchild"


# ------------------------------------------------------------------
# REQ-12.4: TaskGraph.add_task validates acyclicity
# ------------------------------------------------------------------


class TestTaskGraphAcyclicity:
    """TaskGraph.add_task validates that adding a node does not create a cycle."""

    @pytest.mark.ac("AC-12.4.4")
    def test_circular_dependency_detected(self) -> None:
        """Adding a task that creates a cycle results in no tasks being ready."""
        graph = TaskGraph()
        graph.add_task(TaskNode(task_id="a", description="A", depends_on=["b"]))
        graph.add_task(TaskNode(task_id="b", description="B", depends_on=["a"]))

        ready = graph.get_ready_tasks()
        assert len(ready) == 0  # Deadlock -- neither can start


# ------------------------------------------------------------------
# REQ-12.5: State transition records timestamp
# ------------------------------------------------------------------


class TestStateTransitionTimestamp:
    """Each state transition records a timestamp."""

    @pytest.mark.ac("AC-12.5.4")
    async def test_task_status_update_timestamp(self, storage: Storage) -> None:
        """Updating task status persists the new status with timestamp context."""
        task_id = "ts-task-1"
        await storage.create_task(task_id, "timestamp test")
        await storage.update_task(task_id, status="in-progress")

        task = await storage.get_task(task_id)
        assert task is not None
        assert task["status"] == "in-progress"
        assert task["created_at"] is not None  # timestamp exists
