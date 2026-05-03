"""Ollama LLM provider — default backend for Guild."""

from __future__ import annotations

import ollama as ollama_sdk

from guild.core.models import Message, ProviderConfig
from guild.providers.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Ollama backend using the official Python SDK."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = ollama_sdk.AsyncClient(host=config.base_url)

    async def generate(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {
            "model": self.config.model,
            "messages": msgs,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if tools:
            kwargs["tools"] = tools

        resp = await self._client.chat(**kwargs)

        tool_calls = None
        if resp.message.tool_calls:
            tool_calls = [
                {
                    "id": f"call_{i}",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for i, tc in enumerate(resp.message.tool_calls)
            ]

        return LLMResponse(
            content=resp.message.content or "",
            tool_calls=tool_calls,
            input_tokens=resp.prompt_eval_count or 0,
            output_tokens=resp.eval_count or 0,
            model=resp.model,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.list()
            return True
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        resp = await self._client.list()
        return [m.model for m in resp.models]


def create_provider(config: ProviderConfig) -> LLMProvider:
    """Factory — create the right provider based on config."""
    providers = {"ollama": OllamaProvider}
    cls = providers.get(config.name)
    if not cls:
        raise ValueError(f"Unknown provider: {config.name}. Available: {list(providers)}")
    return cls(config)
