"""Sleep/wake survival — detects system sleep and manages recovery.

Uses monotonic time-drift detection: if elapsed time between agent turns
exceeds a threshold, the system likely slept. On wake, re-validates the
LLM provider connection and optionally resumes or pauses the agent.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar

from logger_python import get_logger

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable, Coroutine

    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

__all__ = ["SleepWakeConfig", "SleepWakeDetector", "WakeBehavior"]

logger = get_logger(__name__)

T = TypeVar("T")


class WakeBehavior(str, Enum):
    """What to do after detecting a wake event."""

    RESUME = "resume"
    STAY_PAUSED = "stay-paused"


@dataclass
class SleepWakeConfig:
    """Configuration for sleep/wake detection and recovery."""

    wake_behavior: WakeBehavior = WakeBehavior.RESUME
    sleep_threshold_seconds: float = 60.0
    health_check_retries: int = 5
    health_check_retry_delay: float = 2.0


class SleepWakeDetector:
    """Detects system sleep via time-drift and manages wake recovery.

    Usage in the agent loop:
        1. Call mark_turn_start() at the beginning of each turn.
        2. Call check_for_sleep() at the start of the next turn.
        3. If True, call wait_for_provider_recovery() then decide to
           resume or pause based on should_resume().
    """

    def __init__(self, config: SleepWakeConfig | None = None) -> None:
        self.config = config or SleepWakeConfig()
        self._last_turn_time: float = time.monotonic()
        self._sleep_detected: bool = False

    @property
    def sleep_detected(self) -> bool:
        """Whether a sleep event has been detected since last clear."""
        return self._sleep_detected

    def mark_turn_start(self) -> None:
        """Call at the start of each agent turn."""
        self._last_turn_time = time.monotonic()

    def check_for_sleep(self) -> bool:
        """Check if a sleep occurred since last mark_turn_start.

        Uses time-drift: if monotonic time since last mark exceeds
        the configured threshold, the system likely slept.
        """
        elapsed = time.monotonic() - self._last_turn_time
        if elapsed > self.config.sleep_threshold_seconds:
            self._sleep_detected = True
            logger.warning(
                "Sleep detected: %.1fs elapsed (threshold=%.1fs)",
                elapsed,
                self.config.sleep_threshold_seconds,
            )
            return True
        return False

    def clear_sleep_flag(self) -> None:
        """Reset the sleep-detected flag after handling wake."""
        self._sleep_detected = False

    def should_resume(self) -> bool:
        """Whether to auto-resume after wake (based on config)."""
        return self.config.wake_behavior == WakeBehavior.RESUME

    async def wait_for_provider_recovery(
        self,
        provider: LLMProvider,
        max_retries: int | None = None,
    ) -> bool:
        """Retry health check until provider is back online.

        Returns True if provider recovered within retry limit, False otherwise.
        """
        retries = max_retries or self.config.health_check_retries
        for attempt in range(retries):
            if await provider.health_check():
                logger.debug("Provider recovered after %d attempt(s)", attempt + 1)
                return True
            logger.debug(
                "Health check attempt %d/%d failed, retrying...",
                attempt + 1,
                retries,
            )
            await asyncio.sleep(self.config.health_check_retry_delay)
        logger.warning("Provider did not recover after %d attempts", retries)
        return False

    async def retry_after_sleep(
        self,
        provider: LLMProvider,
        operation: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """Retry an operation after validating provider is back online.

        Catches ConnectionError on first attempt, re-validates the provider,
        then retries once. Raises the original error if recovery fails.
        """
        try:
            return await operation()
        except ConnectionError as exc:
            logger.warning(
                "Connection error during operation, attempting recovery: %s",
                exc,
            )
            recovered = await self.wait_for_provider_recovery(provider)
            if not recovered:
                raise
            return await operation()

    async def log_sleep_event(
        self,
        storage: Storage,
        agent_id: str | None = None,
    ) -> None:
        """Record a sleep-detected event in the audit trail."""
        await storage.log_audit(
            action="sleep_detected",
            agent_id=agent_id,
            details="System sleep detected via time-drift",
        )

    async def log_wake_event(
        self,
        storage: Storage,
        agent_id: str | None = None,
    ) -> None:
        """Record a wake-recovered event in the audit trail."""
        await storage.log_audit(
            action="wake_recovered",
            agent_id=agent_id,
            details="System wake — provider reconnected",
        )
