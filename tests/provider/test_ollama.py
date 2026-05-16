"""Tests for provider/ollama.py — Ollama backend implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from ollama import ResponseError

from guild.provider.base import LLMResponse
from guild.provider.ollama import OllamaProvider, create_provider

pytestmark = pytest.mark.unit


def _make_chat_response(
    content: str = "hello",
    tool_calls: list | None = None,
    prompt_eval_count: int = 10,
    eval_count: int = 5,
    model: str = "gemma4-4b-dense-med",
) -> MagicMock:
    """Build a mock ChatResponse matching the ollama SDK structure."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    response = MagicMock()
    response.message = message
    response.prompt_eval_count = prompt_eval_count
    response.eval_count = eval_count
    response.model = model
    return response


class TestHealthCheck:
    """OllamaProvider.health_check verifies connectivity."""

    async def test_health_check_returns_true_when_reachable(self) -> None:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.list = AsyncMock(return_value=MagicMock())
        provider._client = mock_client

        result = await provider.health_check()

        assert result is True
        mock_client.list.assert_awaited_once()

    async def test_health_check_returns_false_when_unreachable(self) -> None:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.list = AsyncMock(side_effect=ConnectionError("connection refused"))
        provider._client = mock_client

        result = await provider.health_check()

        assert result is False


class TestGenerate:
    """OllamaProvider.generate maps chat responses to LLMResponse."""

    async def test_generate_returns_llm_response_with_text(self) -> None:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(return_value=_make_chat_response(content="Hello, world!"))
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        result = await provider.generate(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello, world!"
        assert result.has_tool_call is False
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.model == "gemma4-4b-dense-med"

    async def test_generate_returns_llm_response_with_tool_calls(self) -> None:
        tool_call = MagicMock()
        tool_call.function.name = "file_read"
        tool_call.function.arguments = {"path": "/tmp/test.txt"}

        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value=_make_chat_response(content="", tool_calls=[tool_call])
        )
        provider._client = mock_client

        messages = [{"role": "user", "content": "Read file"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "file_read",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = await provider.generate(messages, tools=tools)

        assert result.has_tool_call is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "file_read"
        assert result.tool_calls[0]["function"]["arguments"] == {"path": "/tmp/test.txt"}

    async def test_generate_handles_empty_content(self) -> None:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value=_make_chat_response(
                content=None,
                prompt_eval_count=None,
                eval_count=None,
            )
        )
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        result = await provider.generate(messages)

        assert result.content == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0


class TestGenerateEdgeCases:
    """Edge cases: network errors, malformed responses, timeouts."""

    async def test_generate_raises_on_network_error(self) -> None:
        """Network errors (timeout, connection refused) propagate as exceptions."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(side_effect=ConnectionError("Connection refused"))
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        with pytest.raises(ConnectionError, match="Connection refused"):
            await provider.generate(messages)

    async def test_generate_raises_on_timeout(self) -> None:
        """Timeout from the backend propagates."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(side_effect=TimeoutError("Request timed out"))
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        with pytest.raises(TimeoutError):
            await provider.generate(messages)

    async def test_generate_handles_multiple_tool_calls(self) -> None:
        """Multiple tool calls in a single response are all extracted."""
        tc1 = MagicMock()
        tc1.function.name = "file_read"
        tc1.function.arguments = {"path": "a.txt"}
        tc2 = MagicMock()
        tc2.function.name = "file_write"
        tc2.function.arguments = {"path": "b.txt", "content": "x"}

        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value=_make_chat_response(content="", tool_calls=[tc1, tc2])
        )
        provider._client = mock_client

        result = await provider.generate([{"role": "user", "content": "Do two things"}])
        assert result.has_tool_call is True
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0]["function"]["name"] == "file_read"
        assert result.tool_calls[1]["function"]["name"] == "file_write"

    async def test_generate_with_none_tool_calls_returns_no_calls(self) -> None:
        """When model returns no tool_calls attribute (None), result has None."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value=_make_chat_response(content="Just text", tool_calls=None)
        )
        provider._client = mock_client

        result = await provider.generate([{"role": "user", "content": "Hi"}])
        assert result.tool_calls is None
        assert result.has_tool_call is False

    async def test_generate_with_empty_tool_calls_list_returns_none(self) -> None:
        """Empty tool_calls list from model maps to None (falsy)."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value=_make_chat_response(content="done", tool_calls=[])
        )
        provider._client = mock_client

        result = await provider.generate([{"role": "user", "content": "Hi"}])
        # Empty list is falsy, _extract_tool_calls should return None
        assert result.has_tool_call is False


class TestProviderPromptFormatting:
    """Provider-specific prompt formatting handled transparently (REQ-01.4).

    Ollama applies model-specific chat templates server-side, so the client
    does NOT need to do any prompt formatting. This test documents that contract.
    """

    async def test_prompt_formatting_handled_by_ollama(self) -> None:
        """Messages are passed as-is; Ollama applies chat templates per model."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(return_value=_make_chat_response(content="formatted response"))
        provider._client = mock_client

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        result = await provider.generate(messages)

        # Verify messages are passed verbatim to the Ollama client
        # (no client-side template formatting — Ollama does it server-side)
        assert result.content == "formatted response"
        mock_client.chat.assert_awaited_once()


class TestModelNotFound:
    """ResponseError with 'not found' gives a clear error message."""

    async def test_generate_raises_clear_error_on_model_not_found(self) -> None:
        """ResponseError containing 'not found' is re-raised with model name."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="nonexistent-model",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            side_effect=ResponseError("model 'nonexistent-model' not found")
        )
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        with pytest.raises(ResponseError, match="Ollama model not found"):
            await provider.generate(messages)

    async def test_generate_raises_clear_error_on_model_does_not_exist(self) -> None:
        """ResponseError containing 'does not exist' is re-raised with model name."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="missing-model",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            side_effect=ResponseError("model 'missing-model' does not exist")
        )
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        with pytest.raises(ResponseError, match="Ollama model not found"):
            await provider.generate(messages)

    async def test_generate_reraises_other_response_errors(self) -> None:
        """ResponseError without 'not found' is re-raised unmodified."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="test-model",
        )
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(side_effect=ResponseError("internal server error"))
        provider._client = mock_client

        messages = [{"role": "user", "content": "Hi"}]
        with pytest.raises(ResponseError, match="internal server error"):
            await provider.generate(messages)


class TestCreateProvider:
    """create_provider factory builds a configured OllamaProvider."""

    def test_creates_provider_with_defaults(self) -> None:
        provider = create_provider(
            base_url="http://localhost:11434",
            model="gemma4-4b-dense-med",
        )
        assert isinstance(provider, OllamaProvider)
        assert provider.model == "gemma4-4b-dense-med"
        assert provider.base_url == "http://localhost:11434"


# --- Integration tests (real Ollama required) ---


@pytest.mark.integration
class TestOllamaIntegration:
    """Integration tests against a real Ollama instance."""

    BASE_URL = "http://192.168.0.110:11434"
    MODEL = "gemma4-4b-dense-med"

    async def test_real_health_check_succeeds(self) -> None:
        provider = create_provider(base_url=self.BASE_URL, model=self.MODEL)
        result = await provider.health_check()
        assert result is True

    async def test_real_generate_returns_text(self) -> None:
        provider = create_provider(base_url=self.BASE_URL, model=self.MODEL)
        messages = [{"role": "user", "content": "Say exactly: hello world"}]
        result = await provider.generate(messages)

        assert isinstance(result, LLMResponse)
        assert len(result.content) > 0
        assert result.model == self.MODEL

    async def test_real_generate_with_tools_returns_tool_call(self) -> None:
        provider = create_provider(base_url=self.BASE_URL, model=self.MODEL)
        messages = [
            {
                "role": "user",
                "content": "Read the file at /tmp/example.txt",
            }
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "file_read",
                    "description": "Read contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to read",
                            }
                        },
                        "required": ["path"],
                    },
                },
            }
        ]
        result = await provider.generate(messages, tools=tools)

        assert isinstance(result, LLMResponse)
        # Model should call the tool
        assert result.has_tool_call is True
        assert result.tool_calls is not None
        assert len(result.tool_calls) >= 1
        assert result.tool_calls[0]["function"]["name"] == "file_read"
