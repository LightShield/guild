"""Structured event tracing for agent execution (REQ-11.1)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

__all__ = [
    "TraceEvent",
    "Tracer",
]


@dataclass
class TraceEvent:
    """A single trace event in the reasoning chain."""

    timestamp: str
    event_type: str  # "llm_call", "tool_call", "decision", "stuck", "escalation"
    agent_id: str | None = None
    task_id: str | None = None
    details: dict | None = field(default=None)
    duration_ms: int | None = None


class Tracer:
    """Structured event tracer for agent execution.

    Records every LLM call, tool call, and decision point as a structured
    TraceEvent. Events are both stored in-memory and emitted as structured
    JSON log lines.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("guild.trace")
        self._events: list[TraceEvent] = []

    def trace(self, event_type: str, **kwargs: object) -> None:
        """Record a trace event.

        Args:
            event_type: Category of event (llm_call, tool_call, decision,
                stuck, escalation).
            **kwargs: Additional TraceEvent fields (agent_id, task_id,
                details, duration_ms).
        """
        event = TraceEvent(
            timestamp=datetime.now(tz=UTC).isoformat(),
            event_type=event_type,
            **kwargs,  # type: ignore[arg-type]
        )
        self._events.append(event)
        self._logger.info(json.dumps(asdict(event)))

    @property
    def events(self) -> list[TraceEvent]:
        """Return a copy of recorded events."""
        return list(self._events)

    def clear(self) -> None:
        """Clear all recorded events."""
        self._events.clear()
