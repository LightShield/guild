"""Tests for multi-model routing (REQ-17)."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.models import ProviderConfig
from guild.providers.base import LLMResponse
from guild.providers.router import ModelRouter, FallbackChain


class TestModelRouter:
    """REQ-17: Per-agent model assignment and fallback chains."""

    def test_route_to_specific_model(self):
        """Per-agent model override should work."""
        router = ModelRouter(default_config=ProviderConfig(model="llama3.2"))
        config = router.resolve("coder", model_override="codellama")
        assert config.model == "codellama"

    def test_default_model_when_no_override(self):
        router = ModelRouter(default_config=ProviderConfig(model="llama3.2"))
        config = router.resolve("coder")
        assert config.model == "llama3.2"

    def test_block_model_mapping(self):
        """Map block names to specific models."""
        router = ModelRouter(
            default_config=ProviderConfig(model="llama3.2"),
            block_models={"coder": "codellama", "reviewer": "llama3.2"},
        )
        assert router.resolve("coder").model == "codellama"
        assert router.resolve("reviewer").model == "llama3.2"
        assert router.resolve("planner").model == "llama3.2"  # default


class TestFallbackChain:
    """REQ-17.2: Fallback chains when primary model is down."""

    async def test_uses_primary_when_healthy(self):
        primary = AsyncMock()
        primary.health_check = AsyncMock(return_value=True)
        primary.generate = AsyncMock(return_value=LLMResponse(content="from primary"))

        fallback = AsyncMock()

        chain = FallbackChain([primary, fallback])
        provider = await chain.get_healthy_provider()
        assert provider is primary

    async def test_falls_back_when_primary_down(self):
        primary = AsyncMock()
        primary.health_check = AsyncMock(return_value=False)

        fallback = AsyncMock()
        fallback.health_check = AsyncMock(return_value=True)

        chain = FallbackChain([primary, fallback])
        provider = await chain.get_healthy_provider()
        assert provider is fallback

    async def test_returns_none_when_all_down(self):
        p1 = AsyncMock()
        p1.health_check = AsyncMock(return_value=False)
        p2 = AsyncMock()
        p2.health_check = AsyncMock(return_value=False)

        chain = FallbackChain([p1, p2])
        provider = await chain.get_healthy_provider()
        assert provider is None
