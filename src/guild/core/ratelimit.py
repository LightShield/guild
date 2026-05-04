"""Rate limiting & backpressure — prevent resource exhaustion (REQ-20)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

__all__ = ["RateLimiter", "ToolQueue"]


class RateLimiter:
    """Token bucket rate limiter for API calls.

    Args:
        max_calls: Maximum calls per window.
        window_seconds: Time window in seconds.
    """

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._calls: list[float] = []

    async def acquire(self) -> None:
        """Wait until a call is allowed under the rate limit."""
        while True:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self._window]
            if len(self._calls) < self._max:
                self._calls.append(now)
                return
            wait = self._window - (now - self._calls[0])
            await asyncio.sleep(max(0.01, wait))

    @property
    def available(self) -> int:
        """Number of calls available in the current window."""
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < self._window]
        return self._max - len(self._calls)


class ToolQueue:
    """Concurrency-limited queue for tool executions.

    Args:
        max_concurrent: Maximum parallel tool executions.
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0

    async def execute(self, coro: Any) -> Any:
        """Execute a coroutine with concurrency limiting.

        Args:
            coro: Coroutine to execute.

        Returns:
            Result of the coroutine.
        """
        async with self._semaphore:
            self._active += 1
            try:
                return await coro
            finally:
                self._active -= 1

    @property
    def active_count(self) -> int:
        """Number of currently executing tools."""
        return self._active
