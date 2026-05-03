"""LLM provider abstraction — unified interface for all backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

from guild.core.models import Message, ProviderConfig


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[dict] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def has_tool_call(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def generate(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        """Send messages to the model and get a response."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models."""
