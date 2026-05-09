"""Tests for provider/retry.py — retry with exponential backoff."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.provider.base import LLMProvider, LLMResponse
from guild.provider.retry import RetryConfig, RetryProvider

pytestmark = pytest.mark.unit


def _make_mock_provider(name: str = "test-model") -> LLMProvider:
    """Create a mock LLMProvider with a model attribute."""
    provider = AsyncMock(spec=LLMProvider)
    provider.model = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(content=f"response from {name}", model=name)
    )
    provider.health_check = AsyncMock(return_value=True)
    return provider


@pytest.mark.req("REQ-26.4")
class TestRetriesOnConnectionError:
    """RetryProvider retries on ConnectionError."""

    async def test_retries_on_connection_error(self) -> None:
        """Provider retries when underlying generate raises ConnectionError."""
        inner = _make_mock_provider()
        inner.generate = AsyncMock(
            side_effect=[ConnectionError("conn lost"), ConnectionError("conn lost")]
            + [LLMResponse(content="ok", model="test")]
        )
        config = RetryConfig(max_retries=3, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        result = await retry.generate([{"role": "user", "content": "hi"}])

        assert result.content == "ok"
        assert inner.generate.await_count == 3


@pytest.mark.req("REQ-26.4")
class TestSucceedsAfterTransientFailure:
    """RetryProvider succeeds after a transient failure."""

    async def test_succeeds_after_transient_failure(self) -> None:
        """First attempt fails, second succeeds."""
        inner = _make_mock_provider()
        inner.generate = AsyncMock(
            side_effect=[
                TimeoutError("timed out"),
                LLMResponse(content="recovered", model="test"),
            ]
        )
        config = RetryConfig(max_retries=3, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        result = await retry.generate([{"role": "user", "content": "hi"}])

        assert result.content == "recovered"
        assert inner.generate.await_count == 2


@pytest.mark.req("REQ-26.4")
class TestGivesUpAfterMaxRetries:
    """RetryProvider raises after exhausting retries."""

    async def test_gives_up_after_max_retries(self) -> None:
        """After max_retries attempts, the exception propagates."""
        inner = _make_mock_provider()
        inner.generate = AsyncMock(side_effect=ConnectionError("permanent"))
        config = RetryConfig(max_retries=2, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        with pytest.raises(ConnectionError, match="permanent"):
            await retry.generate([{"role": "user", "content": "hi"}])

        # 1 initial + 2 retries = 3 total attempts
        assert inner.generate.await_count == 3


@pytest.mark.req("REQ-26.4")
class TestExponentialBackoffDelays:
    """RetryProvider uses exponential backoff between retries."""

    async def test_exponential_backoff_delays(self) -> None:
        """Delays follow initial * backoff^attempt pattern."""
        inner = _make_mock_provider()
        inner.generate = AsyncMock(side_effect=ConnectionError("fail"))
        config = RetryConfig(
            max_retries=3,
            initial_delay_seconds=1.0,
            backoff_factor=2.0,
            max_delay_seconds=30.0,
        )
        retry = RetryProvider(inner, config)

        sleep_calls: list[float] = []
        with patch("guild.provider.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = lambda d: sleep_calls.append(d)
            with pytest.raises(ConnectionError):
                await retry.generate([{"role": "user", "content": "hi"}])

        # attempt 0 fails -> delay = 1.0 * 2^0 = 1.0
        # attempt 1 fails -> delay = 1.0 * 2^1 = 2.0
        # attempt 2 fails -> delay = 1.0 * 2^2 = 4.0
        assert sleep_calls == [1.0, 2.0, 4.0]


@pytest.mark.req("REQ-26.4")
class TestDoesNotRetryNonRetryableErrors:
    """RetryProvider does not retry non-retryable exceptions."""

    async def test_does_not_retry_non_retryable_errors(self) -> None:
        """ValueError is not retryable — raises immediately."""
        inner = _make_mock_provider()
        inner.generate = AsyncMock(side_effect=ValueError("bad input"))
        config = RetryConfig(max_retries=3, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        with pytest.raises(ValueError, match="bad input"):
            await retry.generate([{"role": "user", "content": "hi"}])

        assert inner.generate.await_count == 1


@pytest.mark.req("REQ-26.4")
class TestHealthCheckRetries:
    """RetryProvider retries health_check on transient failures."""

    async def test_health_check_retries(self) -> None:
        """health_check retries on retryable exceptions."""
        inner = _make_mock_provider()
        inner.health_check = AsyncMock(
            side_effect=[
                ConnectionError("unreachable"),
                True,
            ]
        )
        config = RetryConfig(max_retries=3, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        result = await retry.health_check()

        assert result is True
        assert inner.health_check.await_count == 2


@pytest.mark.req("REQ-01.5")
class TestHealthCheckReturnsFalseAfterAllRetriesFail:
    """health_check returns False after all retries fail."""

    async def test_health_check_returns_false_after_all_retries_fail(self) -> None:
        """When health_check exhausts retries, returns False instead of raising."""
        inner = _make_mock_provider()
        inner.health_check = AsyncMock(side_effect=ConnectionError("down"))
        config = RetryConfig(max_retries=2, initial_delay_seconds=0.01)
        retry = RetryProvider(inner, config)

        result = await retry.health_check()

        assert result is False
        # 1 initial + 2 retries = 3
        assert inner.health_check.await_count == 3
