"""CLI tool provider — shells out to installed CLI tools as LLM providers.

Used as a last-resort escalation provider (e.g., `gemini`, `claude` CLI tools).
Does NOT support structured tool calling — text in/text out only.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from guild.config.constants import CLI_PROVIDER_TIMEOUT_SECONDS
from guild.provider.base import LLMProvider, LLMResponse

__all__ = ["CLIToolProvider"]

logger = logging.getLogger(__name__)


class CLIToolProvider(LLMProvider):
    """Provider that shells out to an installed CLI tool (e.g., gemini, claude).

    Does NOT support structured tool calling — only text in/text out.
    Tools passed to generate() are ignored; the provider sends the
    conversation as a plain text prompt and returns the raw stdout.
    """

    def __init__(
        self,
        command: str,
        model: str | None = None,
        timeout: int = CLI_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        self.command = command
        self.model = model or command
        self._timeout = timeout

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send the conversation to the CLI tool and return the text response.

        Extracts the last user message as the prompt. Tools are ignored
        since CLI providers only support text in/text out.
        """
        prompt = self._extract_prompt(messages)
        cmd = self._build_command(prompt)

        logger.debug("Running CLI provider: %s", cmd)
        stdout = await self._run_command(cmd, prompt)

        return LLMResponse(
            content=stdout.strip(),
            tool_calls=None,
            model=self.model or self.command,
        )

    async def health_check(self) -> bool:
        """Check if the CLI tool is installed and accessible via PATH."""
        return shutil.which(self.command) is not None

    def _extract_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Extract the prompt text from the message list.

        Uses the last user message. Falls back to concatenating all
        messages if no user message is found.
        """
        # Find last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content: str = msg.get("content", "")
                return content

        # Fallback: concatenate all content
        parts: list[str] = []
        for msg in messages:
            text: str = msg.get("content", "")
            if text:
                parts.append(text)
        return "\n".join(parts)

    def _build_command(self, prompt: str) -> list[str]:
        """Build the command list to execute.

        Different CLI tools have different invocation patterns:
        - gemini: gemini -p "prompt"
        - claude: claude -p "prompt"
        """
        cmd = [self.command]
        if self.model and self.model != self.command:
            cmd.extend(["--model", self.model])
        cmd.extend(["-p", prompt])
        return cmd

    async def _run_command(
        self, cmd: list[str], prompt: str
    ) -> str:  # pragma: no cover — requires external CLI tool installed
        """Execute the CLI command and return stdout."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            logger.error("CLI provider %s timed out after %ds", self.command, self._timeout)
            raise TimeoutError(
                f"CLI provider '{self.command}' timed out after {self._timeout}s"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"CLI tool '{self.command}' not found in PATH") from exc

        if process.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            logger.error(
                "CLI provider %s exited with code %d: %s",
                self.command,
                process.returncode,
                stderr_text,
            )
            raise RuntimeError(
                f"CLI tool '{self.command}' failed (exit {process.returncode}): " f"{stderr_text}"
            )

        return stdout_bytes.decode("utf-8", errors="replace")
