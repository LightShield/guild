"""Stuck detection for agent loops (REQ-06.3, REQ-06.4).

Detects when an agent is making no progress: repeated errors,
repeated identical tool calls (loops), or too many turns without success.
"""

from __future__ import annotations

import json
from collections import Counter

__all__ = ["StuckDetector"]

DEFAULT_MAX_REPEATED_ERRORS = 3
DEFAULT_MAX_NO_PROGRESS_TURNS = 10
DEFAULT_MAX_REPEATED_CALLS = 3


class StuckDetector:
    """Detects when an agent is stuck and not making progress.

    Args:
        max_repeated_errors: Consecutive identical errors before stuck.
        max_no_progress_turns: Consecutive failed turns before stuck.
        max_repeated_calls: Identical tool calls before loop detected.
    """

    def __init__(
        self,
        max_repeated_errors: int = DEFAULT_MAX_REPEATED_ERRORS,
        max_no_progress_turns: int = DEFAULT_MAX_NO_PROGRESS_TURNS,
        max_repeated_calls: int = DEFAULT_MAX_REPEATED_CALLS,
    ) -> None:
        self._max_repeated_errors = max_repeated_errors
        self._max_no_progress_turns = max_no_progress_turns
        self._max_repeated_calls = max_repeated_calls
        self._consecutive_errors: list[str] = []
        self._no_progress_count = 0
        self._recent_calls: list[str] = []
        self._reason: str = ""

    def record_turn(self, success: bool, error: str | None = None) -> None:
        """Record the outcome of an agent turn.

        Args:
            success: Whether the turn made progress.
            error: Error message if the turn failed.
        """
        if success:
            self._no_progress_count = 0
            self._consecutive_errors.clear()
        else:
            self._no_progress_count += 1
            if error:
                self._consecutive_errors.append(error)

    def record_tool_call(self, call: dict) -> None:
        """Record a tool call for loop detection.

        Args:
            call: Dict with 'tool' and 'args' keys.
        """
        self._recent_calls.append(json.dumps(call, sort_keys=True))

    def is_stuck(self) -> bool:
        """Check if the agent appears stuck.

        Returns:
            True if stuck condition detected.
        """
        # Check repeated identical errors
        if len(self._consecutive_errors) >= self._max_repeated_errors:
            last_n = self._consecutive_errors[-self._max_repeated_errors:]
            if len(set(last_n)) == 1:
                self._reason = (
                    f"Repeated error {self._max_repeated_errors} times: "
                    f"{last_n[0][:100]}"
                )
                return True

        # Check no progress
        if self._no_progress_count >= self._max_no_progress_turns:
            self._reason = (
                f"No progress for {self._no_progress_count} consecutive turns"
            )
            return True

        # Check tool call loops
        if len(self._recent_calls) >= self._max_repeated_calls:
            last_n = self._recent_calls[-self._max_repeated_calls:]
            if len(set(last_n)) == 1:
                self._reason = (
                    f"Same tool call repeated {self._max_repeated_calls} times"
                )
                return True

        return False

    def get_reason(self) -> str:
        """Get the reason the agent is stuck.

        Returns:
            Human-readable reason string, or empty if not stuck.
        """
        return self._reason

    def reset(self) -> None:
        """Reset all stuck detection state."""
        self._consecutive_errors.clear()
        self._no_progress_count = 0
        self._recent_calls.clear()
        self._reason = ""
