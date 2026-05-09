"""Stuck detection — recognize when no progress is being made (REQ-06.3)."""

from __future__ import annotations

import json
from collections import deque

__all__ = ["StuckDetector"]


class StuckDetector:
    """Detect when an agent loop is stuck and not making progress.

    Tracks three signals:
    - Consecutive identical errors (same error string repeated N times)
    - No-progress turns (N consecutive failures regardless of error)
    - Repeated identical tool calls (same call dict N times in a row)
    """

    def __init__(
        self,
        max_repeated_errors: int = 3,
        max_no_progress_turns: int = 10,
        max_repeated_calls: int = 3,
    ) -> None:
        self._max_repeated_errors = max_repeated_errors
        self._max_no_progress_turns = max_no_progress_turns
        self._max_repeated_calls = max_repeated_calls

        self._consecutive_error_count: int = 0
        self._last_error: str | None = None
        self._no_progress_count: int = 0
        self._recent_calls: deque[str] = deque(maxlen=max_repeated_calls)
        self._reason: str = ""

    def record_turn(self, success: bool, error: str | None = None) -> None:
        """Record the outcome of an agent turn."""
        if success:
            self._consecutive_error_count = 0
            self._last_error = None
            self._no_progress_count = 0
            return

        # Failure turn
        self._no_progress_count += 1

        if error is not None and error == self._last_error:
            self._consecutive_error_count += 1
        else:
            self._consecutive_error_count = 1
            self._last_error = error

    def record_tool_call(self, call: dict) -> None:
        """Record a tool call for repetition detection."""
        serialized = json.dumps(call, sort_keys=True)
        self._recent_calls.append(serialized)

    def is_stuck(self) -> bool:
        """Return True if the agent appears stuck."""
        if self._consecutive_error_count >= self._max_repeated_errors:
            self._reason = (
                f"Repeated identical error {self._consecutive_error_count} times: "
                f"{self._last_error}"
            )
            return True

        if self._no_progress_count >= self._max_no_progress_turns:
            self._reason = f"No progress for {self._no_progress_count} consecutive turns"
            return True

        if self._is_repeated_calls():
            self._reason = "Repeated identical tool call detected"
            return True

        return False

    def get_reason(self) -> str:
        """Return human-readable explanation of why stuck, or empty string."""
        if not self.is_stuck():
            return ""
        return self._reason

    def reset(self) -> None:
        """Clear all state, returning to initial conditions."""
        self._consecutive_error_count = 0
        self._last_error = None
        self._no_progress_count = 0
        self._recent_calls.clear()
        self._reason = ""

    def _is_repeated_calls(self) -> bool:
        """Check if recent calls are all identical and hit the threshold."""
        if len(self._recent_calls) < self._max_repeated_calls:
            return False
        # All entries in the deque must be identical
        first = self._recent_calls[0]
        return all(c == first for c in self._recent_calls)
