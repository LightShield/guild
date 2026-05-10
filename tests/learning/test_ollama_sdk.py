# Learning tests — verify assumptions about ollama SDK behavior.
# If these break on upgrade, our code likely needs updating.
#
# Guild depends on:
#   - AsyncClient(host=...) constructor
#   - ChatResponse.message (Message with .content, .tool_calls)
#   - Message.ToolCall.function.name / .arguments
#   - ListResponse.models attribute

from __future__ import annotations

import pytest
from ollama import AsyncClient, ChatResponse, ListResponse, Message


@pytest.mark.unit
@pytest.mark.req("REQ-03.1")
class TestAsyncClientAcceptsHostParam:
    """Verify AsyncClient(host=...) works — used in OllamaProvider.__init__."""

    def test_async_client_accepts_host_param(self) -> None:
        client = AsyncClient(host="http://localhost:11434")
        # Should construct without error; the host is stored internally.
        assert client is not None


@pytest.mark.unit
@pytest.mark.req("REQ-03.1")
class TestChatResponseHasMessageAttribute:
    """Verify ChatResponse has .message with .content and .tool_calls."""

    def test_chat_response_has_message_attribute(self) -> None:
        msg = Message(role="assistant", content="hello")
        response = ChatResponse(
            model="test-model",
            created_at="2025-01-01T00:00:00Z",
            done=True,
            message=msg,
        )
        # Our code accesses: response.message, response.message.content,
        # response.prompt_eval_count, response.eval_count, response.model
        assert response.message is msg
        assert response.message.content == "hello"
        assert response.message.role == "assistant"
        assert response.model == "test-model"

    def test_chat_response_token_count_fields_exist(self) -> None:
        msg = Message(role="assistant", content="")
        response = ChatResponse(
            model="m",
            created_at="2025-01-01T00:00:00Z",
            done=True,
            message=msg,
            prompt_eval_count=10,
            eval_count=20,
        )
        assert response.prompt_eval_count == 10
        assert response.eval_count == 20

    def test_chat_response_token_counts_default_to_none(self) -> None:
        msg = Message(role="assistant", content="")
        response = ChatResponse(
            model="m",
            created_at="2025-01-01T00:00:00Z",
            done=True,
            message=msg,
        )
        # Our code does `response.prompt_eval_count or 0`
        assert response.prompt_eval_count is None
        assert response.eval_count is None


@pytest.mark.unit
@pytest.mark.req("REQ-03.1")
class TestToolCallsHaveFunctionNameAndArguments:
    """Verify tool_calls have .function.name and .function.arguments."""

    def test_tool_calls_have_function_name_and_arguments(self) -> None:
        tool_call = Message.ToolCall(
            function=Message.ToolCall.Function(
                name="read_file",
                arguments={"path": "/tmp/test.txt"},
            )
        )
        msg = Message(
            role="assistant",
            content="",
            tool_calls=[tool_call],
        )
        assert len(msg.tool_calls) == 1
        call = msg.tool_calls[0]
        assert call.function.name == "read_file"
        assert call.function.arguments == {"path": "/tmp/test.txt"}

    def test_tool_calls_arguments_is_dict_like(self) -> None:
        """Our code does dict(call.function.arguments) — must be iterable as dict."""
        tool_call = Message.ToolCall(
            function=Message.ToolCall.Function(
                name="write_file",
                arguments={"path": "/tmp/out.txt", "content": "data"},
            )
        )
        args = dict(tool_call.function.arguments)
        assert args == {"path": "/tmp/out.txt", "content": "data"}

    def test_message_tool_calls_defaults_to_none(self) -> None:
        """Our code checks `if not raw_calls:` — None should be falsy."""
        msg = Message(role="assistant", content="hi")
        assert not msg.tool_calls


@pytest.mark.unit
@pytest.mark.req("REQ-03.1")
class TestListReturnsModelsAttribute:
    """Verify ListResponse has .models attribute — used in health_check."""

    def test_list_returns_models_attribute(self) -> None:
        response = ListResponse(models=[])
        assert hasattr(response, "models")
        assert response.models == []

    def test_list_response_models_field_is_list(self) -> None:
        """Verify 'models' is in the model_fields — structural contract."""
        assert "models" in ListResponse.model_fields
