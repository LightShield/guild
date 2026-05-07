"""Tests for provider/base.py — LLM provider abstraction contract."""

from __future__ import annotations

import pytest

from guild.provider.base import LLMProvider, LLMResponse

pytestmark = pytest.mark.unit


@pytest.mark.req("REQ-01.1")
class TestLLMResponse:
    """LLMResponse is the unified response contract for all providers."""

    def test_create_with_text_only(self) -> None:
        resp = LLMResponse(content="hello", input_tokens=10, output_tokens=5, model="test")
        assert resp.content == "hello"
        assert resp.has_tool_call is False
        assert resp.tool_calls is None

    def test_create_with_tool_calls(self) -> None:
        calls = [{"id": "1", "function": {"name": "file_read", "arguments": {"path": "x"}}}]
        resp = LLMResponse(
            content="", tool_calls=calls, input_tokens=10, output_tokens=5, model="test"
        )
        assert resp.has_tool_call is True
        assert resp.tool_calls == calls

    def test_has_tool_call_false_for_empty_list(self) -> None:
        resp = LLMResponse(
            content="done", tool_calls=[], input_tokens=0, output_tokens=0, model="test"
        )
        assert resp.has_tool_call is False

    def test_token_counts_default_to_zero(self) -> None:
        resp = LLMResponse(content="x")
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0


@pytest.mark.req("REQ-01.1")
class TestLLMProviderContract:
    """LLMProvider defines the abstract interface all providers must implement."""

    def test_cannot_instantiate_abstract_provider(self) -> None:
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]

    def test_subclass_must_implement_generate(self) -> None:
        class Incomplete(LLMProvider):
            async def health_check(self) -> bool:
                return True

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_health_check(self) -> None:
        class Incomplete(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="")

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self) -> None:
        class Complete(LLMProvider):
            async def generate(self, messages, tools=None):
                return LLMResponse(content="")

            async def health_check(self) -> bool:
                return True

        provider = Complete()
        assert provider is not None


@pytest.mark.req("REQ-01.1")
class TestLLMResponseEdgeCases:
    """Edge cases for LLMResponse behavior."""

    def test_has_tool_call_true_for_non_empty_list(self) -> None:
        """Non-empty tool_calls list means has_tool_call is True."""
        resp = LLMResponse(
            content="",
            tool_calls=[{"function": {"name": "x", "arguments": {}}}],
        )
        assert resp.has_tool_call is True

    def test_has_tool_call_false_for_none(self) -> None:
        """tool_calls=None means has_tool_call is False."""
        resp = LLMResponse(content="hi", tool_calls=None)
        assert resp.has_tool_call is False

    def test_content_can_be_empty_string(self) -> None:
        """Content can be empty string (common with tool-call-only responses)."""
        resp = LLMResponse(content="")
        assert resp.content == ""
        assert resp.has_tool_call is False

    def test_model_defaults_to_empty_string(self) -> None:
        """Model field defaults to empty string."""
        resp = LLMResponse(content="x")
        assert resp.model == ""

    def test_multiple_tool_calls_in_single_response(self) -> None:
        """A response can carry multiple tool calls."""
        calls = [
            {"function": {"name": "file_read", "arguments": {"path": "a.txt"}}},
            {"function": {"name": "file_write", "arguments": {"path": "b.txt", "content": "x"}}},
        ]
        resp = LLMResponse(content="", tool_calls=calls)
        assert resp.has_tool_call is True
        assert len(resp.tool_calls) == 2

    def test_response_with_content_and_tool_calls(self) -> None:
        """A response can have both text content and tool calls simultaneously."""
        calls = [{"function": {"name": "file_read", "arguments": {"path": "a.txt"}}}]
        resp = LLMResponse(content="Let me read that file.", tool_calls=calls)
        assert resp.content == "Let me read that file."
        assert resp.has_tool_call is True
