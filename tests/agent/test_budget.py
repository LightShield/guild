"""Tests for agent/budget.py — budget alerts (REQ-10.4)."""

from __future__ import annotations

import pytest

from guild.agent.budget import BUDGET_ALERT_THRESHOLDS, check_budget_alert


@pytest.mark.unit
class TestBudgetAlertThresholds:
    """BUDGET_ALERT_THRESHOLDS defines expected warning levels."""

    def test_thresholds_are_sorted_ascending(self) -> None:
        """Thresholds must be in ascending order."""
        assert sorted(BUDGET_ALERT_THRESHOLDS) == BUDGET_ALERT_THRESHOLDS

    def test_thresholds_include_100_percent(self) -> None:
        """1.0 (100%) must be a threshold for budget exceeded."""
        assert 1.0 in BUDGET_ALERT_THRESHOLDS


@pytest.mark.unit
class TestCheckBudgetAlert:
    """check_budget_alert fires at correct thresholds."""

    def test_returns_none_when_under_first_threshold(self) -> None:
        """No alert when usage is below the first threshold."""
        result = check_budget_alert(current_tokens=50, budget=1000)
        assert result is None

    def test_returns_none_for_unlimited_budget(self) -> None:
        """No alert when budget is 0 (unlimited)."""
        result = check_budget_alert(current_tokens=9999, budget=0)
        assert result is None

    def test_fires_warning_at_80_percent(self) -> None:
        """Alert fires when usage hits 80% threshold."""
        alerted: set[float] = set()
        result = check_budget_alert(current_tokens=800, budget=1000, already_alerted=alerted)
        assert result is not None
        assert "80%" in result
        assert 0.8 in alerted

    def test_fires_exceeded_at_100_percent(self) -> None:
        """Alert fires 'exceeded' message at 100%."""
        alerted: set[float] = {0.8, 0.9}
        result = check_budget_alert(current_tokens=1000, budget=1000, already_alerted=alerted)
        assert result is not None
        assert "exceeded" in result.lower()

    def test_does_not_repeat_already_alerted_threshold(self) -> None:
        """Same threshold does not fire twice."""
        alerted: set[float] = {0.8}
        result = check_budget_alert(current_tokens=850, budget=1000, already_alerted=alerted)
        assert result is None
