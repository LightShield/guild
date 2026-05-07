"""Tests for provider/cli_provider.py — CLI tool as LLM provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.provider.base import LLMResponse
from guild.provider.cli_provider import CLIToolProvider

pytestmark = pytest.mark.unit


@pytest.mark.req("REQ-17.6")
class TestCLIHealthCheck:
    """CLIToolProvider.health_check verifies the CLI tool is available."""

    async def test_health_check_true_when_command_exists(self) -> None:
        """health_check returns True when the command is found in PATH."""
        provider = CLIToolProvider(command="gemini")

        with patch("guild.provider.cli_provider.shutil.which", return_value="/usr/bin/gemini"):
            result = await provider.health_check()

        assert result is True

    async def test_health_check_false_when_command_missing(self) -> None:
        """health_check returns False when the command is not in PATH."""
        provider = CLIToolProvider(command="nonexistent-tool")

        with patch("guild.provider.cli_provider.shutil.which", return_value=None):
            result = await provider.health_check()

        assert result is False


@pytest.mark.req("REQ-17.6")
class TestCLIGenerate:
    """CLIToolProvider.generate sends prompts to CLI tools."""

    async def test_generate_sends_prompt_to_cli(self) -> None:
        """generate() invokes the CLI tool with the prompt from messages."""
        provider = CLIToolProvider(command="gemini")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"Hello from gemini\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            messages = [{"role": "user", "content": "Say hello"}]
            await provider.generate(messages)

            # Verify the command was called with the prompt
            mock_exec.assert_awaited_once()
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "gemini"
            assert "-p" in call_args
            prompt_idx = list(call_args).index("-p")
            assert call_args[prompt_idx + 1] == "Say hello"

    async def test_generate_returns_stdout_as_content(self) -> None:
        """generate() returns the CLI tool's stdout as the response content."""
        provider = CLIToolProvider(command="claude")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"This is the model response\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            messages = [{"role": "user", "content": "Help me"}]
            result = await provider.generate(messages)

            assert isinstance(result, LLMResponse)
            assert result.content == "This is the model response"
            assert result.model == "claude"

    async def test_tools_ignored_for_cli_provider(self) -> None:
        """Tools are accepted but ignored — CLI providers are text-only."""
        provider = CLIToolProvider(command="gemini")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"text response\n", b""))
        mock_process.returncode = 0

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

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            messages = [{"role": "user", "content": "Read file"}]
            result = await provider.generate(messages, tools=tools)

            assert result.content == "text response"
            assert result.tool_calls is None
            assert result.has_tool_call is False

    async def test_generate_uses_last_user_message(self) -> None:
        """generate() extracts the last user message as the prompt."""
        provider = CLIToolProvider(command="gemini")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"response\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "First message"},
                {"role": "assistant", "content": "OK"},
                {"role": "user", "content": "Second message"},
            ]
            await provider.generate(messages)

            call_args = mock_exec.call_args[0]
            prompt_idx = list(call_args).index("-p")
            assert call_args[prompt_idx + 1] == "Second message"

    async def test_generate_with_model_flag(self) -> None:
        """When model differs from command name, --model flag is added."""
        provider = CLIToolProvider(command="gemini", model="gemini-pro")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"response\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            messages = [{"role": "user", "content": "Hello"}]
            await provider.generate(messages)

            call_args = mock_exec.call_args[0]
            assert "--model" in call_args
            model_idx = list(call_args).index("--model")
            assert call_args[model_idx + 1] == "gemini-pro"

    async def test_generate_raises_on_nonzero_exit(self) -> None:
        """generate() raises RuntimeError when the CLI tool exits non-zero."""
        provider = CLIToolProvider(command="gemini")

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error: API key invalid\n"))
        mock_process.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(RuntimeError, match="API key invalid"):
                await provider.generate(messages)

    async def test_generate_raises_on_command_not_found(self) -> None:
        """generate() raises RuntimeError when the CLI tool isn't found."""
        provider = CLIToolProvider(command="nonexistent")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("No such file"),
        ):
            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(RuntimeError, match="not found in PATH"):
                await provider.generate(messages)

    async def test_generate_raises_on_timeout(self) -> None:
        """generate() raises TimeoutError when the CLI tool takes too long."""
        provider = CLIToolProvider(command="gemini", timeout=5)

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(TimeoutError, match="timed out"):
                await provider.generate(messages)
