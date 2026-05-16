"""Retry with exponential backoff for LLM provider calls (REQ-26.4)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable, Coroutine

from guild.provider.base import LLMProvider, LLMResponse

__all__ = ["RetryConfig", "RetryProvider"]

logger = get_logger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    backoff_factor: float = 2.0
    max_delay_seconds: float = 30.0
    retryable_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: (ConnectionError, TimeoutError, OSError)
    )


class RetryProvider(LLMProvider):
    """Wraps any LLMProvider with retry + exponential backoff."""

    def __init__(
        self,
        provider: LLMProvider,
        config: RetryConfig | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or RetryConfig()

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Call generate with retries on transient failures."""
        return await self._retry(self._provider.generate, messages, tools)

    async def health_check(self) -> bool:
        """Health check with retry — returns False if all retries fail."""
        for attempt in range(self._config.max_retries + 1):
            try:
                return await self._provider.health_check()
            except self._config.retryable_exceptions as exc:
                if attempt == self._config.max_retries:
                    logger.warning(
                        "Health check failed after %d attempts: %s",
                        attempt + 1,
                        exc,
                    )
                    return False
                delay = self._compute_delay(attempt)
                logger.warning(
                    "Health check failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self._config.max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        return False  # pragma: no cover

    async def _retry(
        self,
        fn: Callable[..., Coroutine[Any, Any, LLMResponse]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """Execute fn with retry logic."""
        for attempt in range(self._config.max_retries + 1):
            try:
                return await fn(messages, tools)
            except self._config.retryable_exceptions as exc:
                if attempt == self._config.max_retries:
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    "Provider failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self._config.max_retries + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Unreachable")  # pragma: no cover

    def _compute_delay(self, attempt: int) -> float:
        """Compute delay with exponential backoff, capped at max_delay."""
        delay = self._config.initial_delay_seconds * (self._config.backoff_factor**attempt)
        return min(delay, self._config.max_delay_seconds)
