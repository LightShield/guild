"""Tests for observability/tracing.py — structured event tracing (REQ-11.1, REQ-11.3)."""

from __future__ import annotations

import json
import logging

import pytest

from guild.observability.logging_config import configure_logging
from guild.observability.tracing import Tracer


@pytest.mark.unit
class TestTraceRecording:
    """Tests for trace event recording."""

    def test_trace_records_event(self) -> None:
        """Tracer.trace() stores a TraceEvent in the events list."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="agent-1", task_id="task-1")

        assert len(tracer.events) == 1
        event = tracer.events[0]
        assert event.event_type == "llm_call"
        assert event.agent_id == "agent-1"
        assert event.task_id == "task-1"

    def test_trace_includes_timestamp(self) -> None:
        """Each trace event has a non-empty ISO timestamp."""
        tracer = Tracer()
        tracer.trace("tool_call")

        event = tracer.events[0]
        assert event.timestamp
        # ISO format includes 'T' separator
        assert "T" in event.timestamp

    def test_trace_multiple_event_types(self) -> None:
        """Tracer records events of different types in order."""
        tracer = Tracer()
        tracer.trace("llm_call")
        tracer.trace("tool_call", details={"tool": "file_read"})
        tracer.trace("decision", details={"choice": "proceed"})
        tracer.trace("stuck")
        tracer.trace("escalation")

        assert len(tracer.events) == 5
        types = [e.event_type for e in tracer.events]
        assert types == ["llm_call", "tool_call", "decision", "stuck", "escalation"]

    def test_events_property_returns_copy(self) -> None:
        """The events property returns a copy, not the internal list."""
        tracer = Tracer()
        tracer.trace("llm_call")

        events = tracer.events
        events.clear()

        # Internal list should be unaffected
        assert len(tracer.events) == 1

    def test_clear_removes_all_events(self) -> None:
        """Tracer.clear() empties the events list."""
        tracer = Tracer()
        tracer.trace("llm_call")
        tracer.trace("tool_call")
        tracer.clear()

        assert len(tracer.events) == 0

    def test_trace_stores_details_dict(self) -> None:
        """Details dict is preserved on the event."""
        tracer = Tracer()
        details = {"model": "llama3", "tokens": 150}
        tracer.trace("llm_call", details=details)

        assert tracer.events[0].details == details

    def test_trace_stores_duration_ms(self) -> None:
        """Duration in milliseconds is preserved on the event."""
        tracer = Tracer()
        tracer.trace("llm_call", duration_ms=1234)

        assert tracer.events[0].duration_ms == 1234

    def test_trace_captures_tool_call_details(self) -> None:
        """Trace event preserves full tool call details in the details dict."""
        tracer = Tracer()
        tool_details = {
            "tool_name": "file_write",
            "arguments": {"path": "/tmp/x.py", "content": "hello"},
            "result_success": True,
            "result_output": "Wrote 5 chars",
        }
        tracer.trace("tool_call", agent_id="agent-7", details=tool_details)

        event = tracer.events[0]
        assert event.event_type == "tool_call"
        assert event.details is not None
        assert event.details["tool_name"] == "file_write"
        assert event.details["arguments"]["path"] == "/tmp/x.py"
        assert event.details["result_success"] is True

    def test_trace_captures_duration(self) -> None:
        """Trace event records duration_ms=0 for instantaneous events."""
        tracer = Tracer()
        tracer.trace("decision", duration_ms=0, details={"choice": "skip"})

        event = tracer.events[0]
        assert event.duration_ms == 0
        assert event.details == {"choice": "skip"}

    def test_trace_none_duration_when_not_provided(self) -> None:
        """When duration_ms is not passed, it defaults to None."""
        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")

        event = tracer.events[0]
        assert event.duration_ms is None


@pytest.mark.unit
class TestStructuredLogging:
    """Tests for structured JSON logging output."""

    def test_trace_logs_as_json(self, caplog: pytest.LogCaptureFixture) -> None:
        """Tracer emits each event as a JSON-parseable log line."""
        logger = logging.getLogger("guild.trace.test_json")
        logger.setLevel(logging.DEBUG)
        tracer = Tracer(logger=logger)

        with caplog.at_level(logging.INFO, logger="guild.trace.test_json"):
            tracer.trace("tool_call", agent_id="a1", details={"tool": "file_read"})

        assert len(caplog.records) == 1
        # The message should be valid JSON
        parsed = json.loads(caplog.records[0].message)
        assert parsed["event_type"] == "tool_call"
        assert parsed["agent_id"] == "a1"
        assert parsed["details"]["tool"] == "file_read"

    def test_configure_logging_sets_level(self) -> None:
        """configure_logging() sets the guild logger to the specified level."""
        configure_logging(level="DEBUG")
        guild_logger = logging.getLogger("guild")
        assert guild_logger.level == logging.DEBUG

        configure_logging(level="WARNING")
        assert guild_logger.level == logging.WARNING

    def test_configure_logging_structured_format(self) -> None:
        """With structured=True, the handler uses StructuredFormatter."""
        from guild.observability.logging_config import StructuredFormatter

        configure_logging(level="INFO", structured=True)
        guild_logger = logging.getLogger("guild")

        assert len(guild_logger.handlers) >= 1
        assert isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

    def test_configure_logging_plain_format(self) -> None:
        """With structured=False, the handler uses standard formatter."""
        from guild.observability.logging_config import StructuredFormatter

        configure_logging(level="INFO", structured=False)
        guild_logger = logging.getLogger("guild")

        assert len(guild_logger.handlers) >= 1
        assert not isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

    def test_structured_formatter_produces_valid_json(self) -> None:
        """StructuredFormatter.format() outputs parseable JSON."""
        from guild.observability.logging_config import StructuredFormatter

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="guild.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert parsed["logger"] == "guild.test"
        assert "timestamp" in parsed


# ------------------------------------------------------------------
# REQ-11.5: Log export in standard formats
# ------------------------------------------------------------------


@pytest.mark.unit
class TestLogExport:
    """Tests for JSON and JSONL export of trace events."""

    def test_export_events_json_valid(self) -> None:
        """export_events_json returns a valid JSON array."""
        from guild.observability.tracing import export_events_json

        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1", details={"model": "llama3"})
        tracer.trace("tool_call", agent_id="a1", details={"tool": "file_read"})

        result = export_events_json(tracer.events)

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["event_type"] == "llm_call"
        assert parsed[0]["agent_id"] == "a1"
        assert parsed[1]["event_type"] == "tool_call"
        assert parsed[1]["details"]["tool"] == "file_read"

    def test_export_events_jsonl_one_per_line(self) -> None:
        """export_events_jsonl produces one JSON object per line."""
        from guild.observability.tracing import export_events_jsonl

        tracer = Tracer()
        tracer.trace("llm_call", agent_id="a1")
        tracer.trace("tool_call", agent_id="a2")
        tracer.trace("decision", agent_id="a3")

        result = export_events_jsonl(tracer.events)
        lines = result.strip().split("\n")

        assert len(lines) == 3
        # Each line should be independently parseable JSON
        for _i, line in enumerate(lines):
            parsed = json.loads(line)
            assert "event_type" in parsed
            assert "timestamp" in parsed

        # Verify order
        assert json.loads(lines[0])["agent_id"] == "a1"
        assert json.loads(lines[1])["agent_id"] == "a2"
        assert json.loads(lines[2])["agent_id"] == "a3"

    def test_export_events_json_empty(self) -> None:
        """export_events_json with empty list returns empty JSON array."""
        from guild.observability.tracing import export_events_json

        result = export_events_json([])
        parsed = json.loads(result)
        assert parsed == []

    def test_export_events_jsonl_empty(self) -> None:
        """export_events_jsonl with empty list returns empty string."""
        from guild.observability.tracing import export_events_jsonl

        result = export_events_jsonl([])
        assert result == ""
