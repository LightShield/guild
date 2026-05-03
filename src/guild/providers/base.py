"""LLM provider abstraction — unified interface for all backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from guild.core.models import Message, ProviderConfig

__all__ = ["LLMProvider", "LLMResponse"]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider.

    Attributes:
        content: Text content of the response.
        tool_calls: List of tool calls requested by the model.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens generated.
        model: Model name that produced the response.
    """

    content: str
    tool_calls: list[dict] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def has_tool_call(self) -> bool:
        """Whether the response contains tool calls."""
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract base for LLM providers.

    Args:
        config: Provider configuration.
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def generate(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> LLMResponse:
        """Send messages to the model and get a response.

        Args:
            messages: Conversation history.
            tools: Available tool definitions (JSON schema format).

        Returns:
            Unified LLM response.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable.

        Returns:
            True if the provider is healthy.
        """

    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models.

        Returns:
            List of model name strings.
        """
