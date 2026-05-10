"""Resource-aware scheduling — good neighbor mode.

Detects user activity and system load to throttle agent work:
- FULL mode: no throttling
- POLITE mode: delay between LLM calls when user is active
- STEALTH mode: pause all agent work when user is active
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable

__all__ = [
    "ActivityState",
    "ResourceMonitor",
    "ResourceStatus",
    "ResourceThresholds",
    "SchedulingMode",
]

logger = logging.getLogger(__name__)


class SchedulingMode(str, Enum):
    """Scheduling aggressiveness mode."""

    FULL = "full"
    POLITE = "polite"
    STEALTH = "stealth"


class ActivityState(str, Enum):
    """User activity state."""

    ACTIVE = "active"
    IDLE = "idle"


@dataclass
class ResourceThresholds:
    """Configurable thresholds for resource-aware scheduling."""

    idle_timeout_seconds: float = 300.0
    cpu_threshold_percent: float = 80.0
    polite_delay_seconds: float = 10.0
    poll_interval_seconds: float = 5.0


@dataclass
class ResourceStatus:
    """Current resource and scheduling state snapshot."""

    mode: SchedulingMode
    activity: ActivityState
    cpu_percent: float
    is_throttled: bool
    reason: str = ""


def _default_activity_detector() -> (
    ActivityState
):  # pragma: no cover — platform dependency (psutil optional)
    """Default activity detector using CPU as a proxy.

    MVP: uses psutil if available, otherwise assumes IDLE.
    """
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        if cpu > 80.0:
            return ActivityState.ACTIVE
    except ImportError:
        pass
    return ActivityState.IDLE


def _default_cpu_reader() -> float:  # pragma: no cover — platform dependency (psutil optional)
    """Default CPU reader using psutil, falling back to 0.0."""
    try:
        import psutil

        return psutil.cpu_percent(interval=0.1)
    except ImportError:
        return 0.0


class ResourceMonitor:
    """Monitors system resources and throttles agent work accordingly.

    Integration point: the agent loop calls wait_if_throttled() before
    each LLM call. Behavior depends on the scheduling mode and current
    user activity state.
    """

    def __init__(
        self,
        mode: SchedulingMode = SchedulingMode.POLITE,
        thresholds: ResourceThresholds | None = None,
        activity_detector: Callable[[], ActivityState] | None = None,
        cpu_reader: Callable[[], float] | None = None,
    ) -> None:
        self.mode = mode
        self.thresholds = thresholds or ResourceThresholds()
        self._activity_detector = activity_detector or _default_activity_detector
        self._cpu_reader = cpu_reader or _default_cpu_reader

    def detect_activity(self) -> ActivityState:
        """Return current user activity state via injected detector."""
        return self._activity_detector()

    def get_cpu_percent(self) -> float:
        """Return current CPU utilization via injected reader."""
        return self._cpu_reader()

    def get_status(self) -> ResourceStatus:
        """Return a snapshot of current resource and scheduling state."""
        activity = self.detect_activity()
        cpu = self.get_cpu_percent()
        is_throttled = self._should_throttle(activity)
        reason = self._throttle_reason(activity, is_throttled)
        return ResourceStatus(
            mode=self.mode,
            activity=activity,
            cpu_percent=cpu,
            is_throttled=is_throttled,
            reason=reason,
        )

    async def wait_if_throttled(self) -> None:
        """Called by agent loop before each LLM call. Blocks if throttled.

        - FULL mode: return immediately
        - POLITE mode: if user is active, sleep for polite_delay_seconds
        - STEALTH mode: if user is active, block until idle
        """
        if self.mode == SchedulingMode.FULL:
            return

        if self.mode == SchedulingMode.POLITE:
            await self._wait_polite()
            return

        if self.mode == SchedulingMode.STEALTH:  # pragma: no branch
            await self._wait_stealth()
            return

    async def _wait_polite(self) -> None:
        """Polite mode: delay if user is active."""
        activity = self.detect_activity()
        if activity == ActivityState.ACTIVE:
            delay = self.thresholds.polite_delay_seconds
            logger.debug("Polite mode: user active, delaying %.1fs", delay)
            await asyncio.sleep(delay)

    async def _wait_stealth(self) -> None:
        """Stealth mode: block until user is idle."""
        while self.detect_activity() == ActivityState.ACTIVE:
            logger.debug(
                "Stealth mode: user active, polling in %.1fs",
                self.thresholds.poll_interval_seconds,
            )
            await asyncio.sleep(self.thresholds.poll_interval_seconds)

    def _should_throttle(self, activity: ActivityState) -> bool:
        """Determine if throttling is active given current state."""
        if self.mode == SchedulingMode.FULL:
            return False
        return activity == ActivityState.ACTIVE

    def _throttle_reason(self, activity: ActivityState, is_throttled: bool) -> str:
        """Generate human-readable reason for current throttle state."""
        if not is_throttled:
            return ""
        if self.mode == SchedulingMode.POLITE:
            return "user active — polite delay applied"
        if self.mode == SchedulingMode.STEALTH:
            return "user active — paused until idle"
        return ""  # pragma: no cover — defensive unreachable
