"""Budget alerts for token usage monitoring (REQ-10.4).

Provides threshold-based alerts when an agent approaches its token budget.
"""

from __future__ import annotations

import logging

__all__ = [
    "BUDGET_ALERT_THRESHOLDS",
    "check_budget_alert",
]

logger = logging.getLogger(__name__)

BUDGET_ALERT_THRESHOLDS = [0.8, 0.9, 1.0]


def check_budget_alert(
    current_tokens: int,
    budget: int,
    already_alerted: set[float] | None = None,
) -> str | None:
    """Check if a budget threshold has been crossed.

    Returns an alert message if a new threshold is crossed,
    None otherwise. The already_alerted set tracks which
    thresholds have already fired (mutated in-place).

    Args:
        current_tokens: Current total token usage.
        budget: The token budget (0 means unlimited).
        already_alerted: Set of thresholds already triggered.
    """
    if budget <= 0:
        return None

    if already_alerted is None:
        already_alerted = set()

    ratio = current_tokens / budget

    for threshold in BUDGET_ALERT_THRESHOLDS:
        if ratio >= threshold and threshold not in already_alerted:
            already_alerted.add(threshold)
            pct = int(threshold * 100)
            if threshold >= 1.0:
                msg = f"Budget exceeded: {current_tokens}/{budget} tokens " f"({pct}% of budget)"
            else:
                msg = f"Budget warning: {current_tokens}/{budget} tokens " f"({pct}% of budget)"
            logger.warning(msg)
            return msg

    return None
