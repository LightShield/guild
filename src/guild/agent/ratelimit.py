"""Rate limiting and tool queue for agent execution (REQ-20.1, REQ-20.2)."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

__all__ = [
    "RateLimiter",
    "ToolQueue",
]


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
            if wait > 0:
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
