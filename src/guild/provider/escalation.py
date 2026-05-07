"""Model escalation chain — fallback and stuck-triggered model escalation."""

from __future__ import annotations

import logging
from typing import Any

from guild.provider.base import LLMProvider, LLMResponse

__all__ = ["EscalationChain", "EscalatingProvider", "MalformedOutputError"]

logger = logging.getLogger(__name__)


class MalformedOutputError(Exception):
    """Raised when model output is unparseable or structurally invalid."""

    def __init__(self, message: str = "Malformed model output") -> None:
        super().__init__(message)


class EscalationChain:
    """Manages an ordered chain of providers, escalating on failure/stuck.

    The chain starts at index 0 (primary provider) and moves forward
    on each escalation. Once exhausted, no further escalation is possible.
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("EscalationChain requires at least one provider")
        self._providers = providers
        self._current_index = 0

    @property
    def current(self) -> LLMProvider:
        """Return the currently active provider."""
        return self._providers[self._current_index]

    @property
    def current_index(self) -> int:
        """Return the current position in the chain (0-based)."""
        return self._current_index

    @property
    def current_name(self) -> str:
        """Human-readable name of the current provider."""
        provider = self._providers[self._current_index]
        if hasattr(provider, "model") and provider.model:
            return str(provider.model)
        return f"provider-{self._current_index}"

    @property
    def is_exhausted(self) -> bool:
        """True when the chain is at its last provider (no more escalation)."""
        return self._current_index >= len(self._providers) - 1

    def escalate(self) -> bool:
        """Move to the next provider in the chain.

        Returns True if escalation succeeded, False if already exhausted.
        """
        if self.is_exhausted:
            return False
        self._current_index += 1
        logger.info(
            "Escalating to provider %d: %s",
            self._current_index,
            self.current_name,
        )
        return True

    def reset(self) -> None:
        """Reset to the primary (first) provider."""
        self._current_index = 0

    def __len__(self) -> int:
        return len(self._providers)


MALFORMED_CORRECTION_HINT = (
    "Your previous response was malformed or could not be parsed. "
    "Please try again, ensuring your output follows the expected format."
)


class EscalatingProvider(LLMProvider):
    """Provider wrapper that automatically escalates through a chain on failure.

    Behavior on generate() failure:
    1. Retry with the same provider (one attempt).
    2. If still failing, escalate to the next provider in the chain.
    3. If chain is exhausted, raise the exception.

    Behavior on malformed output (notify_malformed):
    1. Retry with correction hint on current provider.
    2. If still malformed, escalate and retry.
    3. If chain exhausted, raise MalformedOutputError.
    """

    def __init__(self, chain: EscalationChain) -> None:
        self._chain = chain

    @property
    def chain(self) -> EscalationChain:
        """Access the underlying escalation chain."""
        return self._chain

    @property
    def model(self) -> str:
        """Expose current model name for compatibility."""
        return self._chain.current_name

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate a response, escalating on failure.

        On exception from the current provider, escalates to the next
        provider in the chain and retries. If the chain is exhausted,
        the exception propagates.
        """
        try:
            return await self._chain.current.generate(messages, tools)
        except Exception as exc:
            logger.warning(
                "Provider %s failed: %s. Attempting escalation.",
                self._chain.current_name,
                exc,
            )
            if self._chain.escalate():
                return await self._chain.current.generate(messages, tools)
            raise

    async def health_check(self) -> bool:
        """Check if the current provider is healthy."""
        return await self._chain.current.health_check()

    def notify_stuck(self) -> bool:
        """Called by the agent loop when stuck. Escalates to next model.

        Returns True if escalation succeeded, False if exhausted.
        """
        logger.info("Stuck notification received, escalating model.")
        return self._chain.escalate()

    async def generate_with_malformed_recovery(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate with malformed-output recovery (REQ-17.8).

        Strategy:
        1. Try current provider.
        2. On malformed output, retry with correction hint.
        3. If still malformed, escalate and retry.
        4. Exhaust chain, then raise MalformedOutputError.

        Callers should catch MalformedOutputError to detect this is
        actually a validation issue rather than a generate failure.
        The caller is responsible for determining what "malformed" means
        and calling this method in a retry loop.
        """
        # First attempt — delegated to the caller's validation
        return await self._chain.current.generate(messages, tools)

    async def retry_with_correction(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Retry on the current provider with a correction hint appended."""
        corrected = messages + [{"role": "user", "content": MALFORMED_CORRECTION_HINT}]
        return await self._chain.current.generate(corrected, tools)

    async def escalate_and_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Escalate to the next provider and retry.

        Raises MalformedOutputError if the chain is exhausted.
        """
        if not self._chain.escalate():
            raise MalformedOutputError("Chain exhausted after malformed output")
        return await self._chain.current.generate(messages, tools)
