"""Multi-model routing — per-agent model assignment and fallback chains (REQ-17)."""

from __future__ import annotations

from guild.core.models import ProviderConfig
from guild.providers.base import LLMProvider

__all__ = ["FallbackChain", "ModelRouter"]


class ModelRouter:
    """Routes agents to the right model based on block name or override.

    Args:
        default_config: Default provider config.
        block_models: Mapping of block name → model name override.
    """

    def __init__(
        self,
        default_config: ProviderConfig,
        block_models: dict[str, str] | None = None,
    ) -> None:
        self._default = default_config
        self._block_models = block_models or {}

    def resolve(self, block_name: str, model_override: str | None = None) -> ProviderConfig:
        """Resolve the provider config for a block.

        Args:
            block_name: Name of the block.
            model_override: Explicit model override (highest priority).

        Returns:
            ProviderConfig with the resolved model.
        """
        model = model_override or self._block_models.get(block_name) or self._default.model
        return ProviderConfig(
            name=self._default.name,
            base_url=self._default.base_url,
            model=model,
            temperature=self._default.temperature,
            max_tokens=self._default.max_tokens,
        )


class FallbackChain:
    """Fallback chain — try providers in order until one is healthy.

    Args:
        providers: Ordered list of providers (primary first).
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = providers

    async def get_healthy_provider(self) -> LLMProvider | None:
        """Get the first healthy provider in the chain.

        Returns:
            A healthy LLMProvider, or None if all are down.
        """
        for provider in self._providers:
            if await provider.health_check():
                return provider
        return None
