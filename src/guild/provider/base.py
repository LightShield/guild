"""LLM provider abstraction — unified interface for all backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

__all__ = ["LLMProvider", "LLMResponse"]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[dict[str, Any]] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def has_tool_call(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """Send messages to the model and get a response."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
