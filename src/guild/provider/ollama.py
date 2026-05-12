"""Ollama LLM provider — default backend using ollama Python SDK."""

from __future__ import annotations

import logging
from typing import Any

from ollama import AsyncClient, RequestError, ResponseError

from guild.provider.base import LLMProvider, LLMResponse

__all__ = ["OllamaProvider", "create_provider"]

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama backend using the official ollama Python SDK (AsyncClient)."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url
        self.model = model
        self._client = AsyncClient(host=base_url)

    async def health_check(self) -> bool:
        """Check if the Ollama server is reachable by listing models."""
        try:
            await self._client.list()
            return True
        except (ConnectionError, TimeoutError, OSError, RequestError, ResponseError) as exc:
            logger.warning("Ollama health check failed: %s", exc)
            return False

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send messages to Ollama and return a unified LLMResponse."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.chat(**kwargs)
        except ResponseError as exc:
            # Surface model-not-found as a clear error message
            err_str = str(exc).lower()
            if "not found" in err_str or "does not exist" in err_str:
                msg = f"Ollama model not found: '{self.model}'"
                raise ResponseError(msg) from exc
            raise
        return self._map_response(response)

    def _map_response(self, response: Any) -> LLMResponse:
        """Convert an ollama ChatResponse to our unified LLMResponse."""
        message = response.message
        content = message.content or ""
        tool_calls = self._extract_tool_calls(message.tool_calls)
        input_tokens = response.prompt_eval_count or 0
        output_tokens = response.eval_count or 0
        model = response.model or self.model

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )

    def _extract_tool_calls(self, raw_calls: Any) -> list[dict[str, Any]] | None:
        """Map ollama tool_calls to our standard format."""
        if not raw_calls:
            return None

        result: list[dict[str, Any]] = []
        for call in raw_calls:
            result.append(
                {
                    "function": {
                        "name": call.function.name,
                        "arguments": dict(call.function.arguments),
                    }
                }
            )
        return result


def create_provider(base_url: str, model: str) -> OllamaProvider:
    """Factory function to create a configured OllamaProvider."""
    return OllamaProvider(base_url=base_url, model=model)
