"""Tests for agent/stuck.py — stuck detection (REQ-06.3)."""

from __future__ import annotations

import pytest

from guild.agent.stuck import StuckDetector


@pytest.mark.unit
@pytest.mark.req("REQ-06.3")
class TestStuckDetector:
    """StuckDetector recognizes when no progress is being made."""

    def test_not_stuck_initially(self) -> None:
        """A freshly created detector is not stuck."""
        detector = StuckDetector()
        assert not detector.is_stuck()

    def test_repeated_identical_errors_triggers_stuck(self) -> None:
        """N consecutive identical error strings triggers stuck state."""
        detector = StuckDetector(max_repeated_errors=3)
        for _ in range(3):
            detector.record_turn(success=False, error="Connection refused")
        assert detector.is_stuck()

    def test_different_errors_do_not_trigger_stuck(self) -> None:
        """Different error strings do not trigger stuck detection."""
        detector = StuckDetector(max_repeated_errors=3)
        detector.record_turn(success=False, error="Error A")
        detector.record_turn(success=False, error="Error B")
        detector.record_turn(success=False, error="Error C")
        assert not detector.is_stuck()

    def test_no_progress_turns_triggers_stuck(self) -> None:
        """N consecutive failure turns (regardless of error) triggers stuck."""
        detector = StuckDetector(max_no_progress_turns=5)
        for i in range(5):
            detector.record_turn(success=False, error=f"Error {i}")
        assert detector.is_stuck()

    def test_successful_turn_resets_no_progress_count(self) -> None:
        """A successful turn resets the no-progress counter."""
        detector = StuckDetector(max_no_progress_turns=5)
        for i in range(4):
            detector.record_turn(success=False, error=f"Error {i}")
        detector.record_turn(success=True)
        for i in range(4):
            detector.record_turn(success=False, error=f"Error {i}")
        assert not detector.is_stuck()

    def test_repeated_tool_calls_triggers_stuck(self) -> None:
        """N identical tool calls triggers stuck state."""
        detector = StuckDetector(max_repeated_calls=3)
        call = {"name": "file_read", "arguments": {"path": "a.txt"}}
        for _ in range(3):
            detector.record_tool_call(call)
        assert detector.is_stuck()

    def test_different_tool_calls_do_not_trigger_stuck(self) -> None:
        """Different tool calls do not trigger stuck detection."""
        detector = StuckDetector(max_repeated_calls=3)
        detector.record_tool_call({"name": "file_read", "arguments": {"path": "a.txt"}})
        detector.record_tool_call({"name": "file_read", "arguments": {"path": "b.txt"}})
        detector.record_tool_call({"name": "file_write", "arguments": {"path": "c.txt"}})
        assert not detector.is_stuck()

    def test_get_reason_returns_description(self) -> None:
        """get_reason returns a non-empty string describing why stuck."""
        detector = StuckDetector(max_repeated_errors=2)
        detector.record_turn(success=False, error="timeout")
        detector.record_turn(success=False, error="timeout")
        assert detector.is_stuck()
        reason = detector.get_reason()
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_reset_clears_all_state(self) -> None:
        """reset() brings the detector back to initial state."""
        detector = StuckDetector(max_repeated_errors=2)
        detector.record_turn(success=False, error="timeout")
        detector.record_turn(success=False, error="timeout")
        assert detector.is_stuck()
        detector.reset()
        assert not detector.is_stuck()
        assert detector.get_reason() == ""

    def test_configurable_thresholds(self) -> None:
        """Custom thresholds are respected."""
        detector = StuckDetector(
            max_repeated_errors=5,
            max_no_progress_turns=20,
            max_repeated_calls=4,
        )
        # 3 repeated errors is not enough with threshold 5
        for _ in range(3):
            detector.record_turn(success=False, error="same")
        assert not detector.is_stuck()
        # 4 repeated calls is enough with threshold 4
        call = {"name": "tool", "arguments": {}}
        for _ in range(4):
            detector.record_tool_call(call)
        assert detector.is_stuck()

    def test_success_resets_consecutive_errors(self) -> None:
        """A successful turn resets the consecutive identical error counter."""
        detector = StuckDetector(max_repeated_errors=3)
        detector.record_turn(success=False, error="same error")
        detector.record_turn(success=False, error="same error")
        # One success in between should reset the counter
        detector.record_turn(success=True)
        detector.record_turn(success=False, error="same error")
        detector.record_turn(success=False, error="same error")
        assert not detector.is_stuck()
