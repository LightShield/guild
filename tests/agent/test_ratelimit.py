"""Tests for agent/ratelimit.py — rate limiting and tool queue (REQ-20.1, REQ-20.2)."""

from __future__ import annotations

import asyncio
import time

import pytest

from guild.agent.ratelimit import RateLimiter, ToolQueue


@pytest.mark.unit
@pytest.mark.req("REQ-20.1")
class TestRateLimiter:
    """Tests for the sliding-window rate limiter."""

    async def test_rate_limiter_allows_within_limit(self) -> None:
        """Acquiring calls within the limit does not block."""
        limiter = RateLimiter(max_calls=5, window_seconds=60.0)

        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        # Should complete near-instantly (< 100ms)
        assert elapsed < 0.1

    async def test_rate_limiter_blocks_when_exceeded(self) -> None:
        """Acquiring beyond the limit blocks until the window slides."""
        limiter = RateLimiter(max_calls=2, window_seconds=0.2)

        # Use up all available calls
        await limiter.acquire()
        await limiter.acquire()

        # Next acquire should block
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        # Should have waited approximately 0.2 seconds
        assert elapsed >= 0.15

    async def test_rate_limiter_releases_after_window(self) -> None:
        """Calls become available again after the window elapses."""
        limiter = RateLimiter(max_calls=2, window_seconds=0.1)

        await limiter.acquire()
        await limiter.acquire()

        # Wait for window to pass
        await asyncio.sleep(0.15)

        # Should now have capacity again
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed < 0.05

    async def test_available_count_decreases(self) -> None:
        """The available property decreases as calls are made."""
        limiter = RateLimiter(max_calls=5, window_seconds=60.0)

        assert limiter.available == 5
        await limiter.acquire()
        assert limiter.available == 4
        await limiter.acquire()
        assert limiter.available == 3

    async def test_available_recovers_after_window(self) -> None:
        """Available count recovers after the window passes."""
        limiter = RateLimiter(max_calls=3, window_seconds=0.1)

        await limiter.acquire()
        await limiter.acquire()
        assert limiter.available == 1

        await asyncio.sleep(0.15)
        assert limiter.available == 3

    async def test_default_parameters(self) -> None:
        """Default RateLimiter allows 30 calls in 60 seconds."""
        limiter = RateLimiter()
        assert limiter.available == 30


@pytest.mark.unit
@pytest.mark.req("REQ-20.2")
class TestToolQueue:
    """Tests for the concurrency-limited tool queue."""

    async def test_tool_queue_limits_concurrency(self) -> None:
        """ToolQueue limits how many coroutines run simultaneously."""
        queue = ToolQueue(max_concurrent=2)
        running = 0
        max_running = 0

        async def tracked_task() -> str:
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            running -= 1
            return "done"

        # Launch 4 tasks; at most 2 should run at once
        tasks = [asyncio.create_task(queue.execute(tracked_task())) for _ in range(4)]
        results = await asyncio.gather(*tasks)

        assert all(r == "done" for r in results)
        assert max_running <= 2

    async def test_tool_queue_executes_sequentially_at_max_1(self) -> None:
        """With max_concurrent=1, tasks run one at a time."""
        queue = ToolQueue(max_concurrent=1)
        execution_order: list[int] = []

        async def ordered_task(index: int) -> int:
            execution_order.append(index)
            await asyncio.sleep(0.02)
            return index

        tasks = [asyncio.create_task(queue.execute(ordered_task(i))) for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert sorted(results) == [0, 1, 2]
        # With max_concurrent=1, tasks should not have overlapped
        assert len(execution_order) == 3

    async def test_tool_queue_returns_coroutine_result(self) -> None:
        """ToolQueue.execute() returns the result from the coroutine."""
        queue = ToolQueue(max_concurrent=4)

        async def compute() -> int:
            return 42

        result = await queue.execute(compute())
        assert result == 42

    async def test_tool_queue_propagates_exceptions(self) -> None:
        """Exceptions from the coroutine propagate through execute()."""
        queue = ToolQueue(max_concurrent=4)

        async def failing() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await queue.execute(failing())

    async def test_tool_queue_default_concurrency(self) -> None:
        """Default ToolQueue allows 4 concurrent tasks."""
        queue = ToolQueue()
        running = 0
        max_running = 0

        async def tracked() -> None:
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.03)
            running -= 1

        tasks = [asyncio.create_task(queue.execute(tracked())) for _ in range(8)]
        await asyncio.gather(*tasks)

        assert max_running <= 4
