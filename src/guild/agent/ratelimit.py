"""Rate limiting and tool queue for agent execution (REQ-20.1, REQ-20.2)."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Coroutine

__all__ = [
    "BackpressureManager",
    "RateLimiter",
    "ToolQueue",
]


class BackpressureManager:
    """Pauses low-priority work when system is loaded (REQ-20.3).

    Uses a semaphore to limit concurrent work. When the semaphore is
    fully acquired, subsequent acquire() calls block until a slot
    is released.
    """

    def __init__(self, max_concurrent: int = 1) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0

    async def acquire(self, priority: int = 0) -> None:
        """Wait until this priority level can proceed.

        Args:
            priority: Higher values indicate higher priority (unused
                      for ordering in this implementation; all waiters
                      are FIFO via the semaphore).
        """
        await self._semaphore.acquire()
        self._active += 1

    def release(self) -> None:
        """Release a slot, allowing a waiting acquire to proceed."""
        if self._active > 0:
            self._active -= 1
        self._semaphore.release()

    @property
    def is_under_pressure(self) -> bool:
        """True when all concurrent slots are occupied."""
        return self._active >= self._max_concurrent


class RateLimiter:
    """Sliding-window rate limiter for LLM API calls.

    Enforces a maximum number of calls within a rolling time window.
    Callers await acquire() before making an API call.
    """

    def __init__(
        self,
        max_calls: int = 30,
        window_seconds: float = 60.0,
    ) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._calls: list[float] = []

    async def acquire(self) -> None:
        """Wait until a call is allowed under the rate limit."""
        while True:
            self._prune()
            if len(self._calls) < self._max:
                self._calls.append(time.monotonic())
                return
            # Calculate wait time until the oldest call exits the window
            oldest = self._calls[0]
            wait = self._window - (time.monotonic() - oldest)
            if wait > 0:  # pragma: no branch — defensive: prune() evicts expired
                await asyncio.sleep(wait)
            self._prune()

    @property
    def available(self) -> int:
        """Return the number of calls available in the current window."""
        self._prune()
        return max(0, self._max - len(self._calls))

    def _prune(self) -> None:
        """Remove calls that have fallen outside the time window."""
        cutoff = time.monotonic() - self._window
        self._calls = [t for t in self._calls if t > cutoff]


class ToolQueue:
    """Concurrency limiter for parallel tool executions.

    Wraps a semaphore to bound how many tool coroutines run simultaneously.
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent

    async def execute(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Execute a coroutine with concurrency limiting.

        Args:
            coro: The coroutine to execute under the concurrency limit.

        Returns:
            The result of the coroutine.
        """
        async with self._semaphore:
            return await coro
