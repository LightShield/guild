"""Tests for stuck detection (REQ-06.3, REQ-06.4)."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.stuck import StuckDetector


class TestStuckDetector:
    """REQ-06.3: Recognize when no progress is being made."""

    def test_not_stuck_initially(self):
        detector = StuckDetector(max_repeated_errors=3, max_no_progress_turns=5)
        assert detector.is_stuck() is False

    def test_detects_repeated_errors(self):
        """Same error message repeated N times = stuck."""
        detector = StuckDetector(max_repeated_errors=3)
        detector.record_turn(success=False, error="Error: file not found")
        detector.record_turn(success=False, error="Error: file not found")
        assert detector.is_stuck() is False
        detector.record_turn(success=False, error="Error: file not found")
        assert detector.is_stuck() is True

    def test_different_errors_not_stuck(self):
        """Different errors don't trigger stuck detection."""
        detector = StuckDetector(max_repeated_errors=3)
        detector.record_turn(success=False, error="Error: file not found")
        detector.record_turn(success=False, error="Error: permission denied")
        detector.record_turn(success=False, error="Error: timeout")
        assert detector.is_stuck() is False

    def test_detects_no_progress(self):
        """N turns with no successful tool calls = stuck."""
        detector = StuckDetector(max_no_progress_turns=3)
        detector.record_turn(success=False)
        detector.record_turn(success=False)
        assert detector.is_stuck() is False
        detector.record_turn(success=False)
        assert detector.is_stuck() is True

    def test_success_resets_counter(self):
        """A successful turn resets the no-progress counter."""
        detector = StuckDetector(max_no_progress_turns=3)
        detector.record_turn(success=False)
        detector.record_turn(success=False)
        detector.record_turn(success=True)  # reset
        detector.record_turn(success=False)
        detector.record_turn(success=False)
        assert detector.is_stuck() is False

    def test_detects_loop(self):
        """Same tool called with same args repeatedly = loop."""
        detector = StuckDetector(max_repeated_calls=3)
        call = {"tool": "file_read", "args": {"path": "/tmp/x"}}
        detector.record_tool_call(call)
        detector.record_tool_call(call)
        assert detector.is_stuck() is False
        detector.record_tool_call(call)
        assert detector.is_stuck() is True

    def test_different_calls_not_loop(self):
        detector = StuckDetector(max_repeated_calls=3)
        detector.record_tool_call({"tool": "file_read", "args": {"path": "/tmp/a"}})
        detector.record_tool_call({"tool": "file_read", "args": {"path": "/tmp/b"}})
        detector.record_tool_call({"tool": "file_read", "args": {"path": "/tmp/c"}})
        assert detector.is_stuck() is False

    def test_get_reason(self):
        """When stuck, should provide a reason string."""
        detector = StuckDetector(max_repeated_errors=2)
        detector.record_turn(success=False, error="Error: boom")
        detector.record_turn(success=False, error="Error: boom")
        assert detector.is_stuck() is True
        reason = detector.get_reason()
        assert "repeated" in reason.lower() or "error" in reason.lower()

    def test_reset(self):
        """Reset clears all state."""
        detector = StuckDetector(max_repeated_errors=2)
        detector.record_turn(success=False, error="Error: boom")
        detector.record_turn(success=False, error="Error: boom")
        assert detector.is_stuck() is True
        detector.reset()
        assert detector.is_stuck() is False
