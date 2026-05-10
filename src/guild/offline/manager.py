"""Offline-first support: connectivity checks, local models, offline docs."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

__all__ = ["OfflineManager"]

logger = logging.getLogger(__name__)

_OFFLINE_DOCS: dict[str, str] = {
    "getting-started": (
        "Guild is a locally-focused agent harness.\n"
        "Run 'guild init' to set up a project, then 'guild task' to run tasks.\n"
        "All core functionality works offline with local Ollama models."
    ),
    "models": (
        "Guild uses Ollama for local LLM inference.\n"
        "Use 'ollama list' to see available models.\n"
        "Use 'ollama pull <model>' to download new models.\n"
        "Recommended: qwen2.5-coder, codellama, deepseek-coder."
    ),
    "commands": (
        "guild init      - Initialize .guild/ in current directory\n"
        "guild task      - Run a task\n"
        "guild chat      - Interactive chat\n"
        "guild status    - Project status\n"
        "guild serve     - Start web GUI on :8585"
    ),
    "troubleshooting": (
        "If Ollama is not responding:\n"
        "  1. Check 'ollama serve' is running\n"
        "  2. Verify model is pulled: 'ollama list'\n"
        "  3. Check port 11434 is accessible\n"
        "If guild commands fail, try 'guild init' again."
    ),
}


class LLMProviderProtocol(Protocol):
    """Minimal protocol for the provider dependency."""

    async def health_check(self) -> bool: ...  # pragma: no cover — protocol stub


class OfflineManager:
    """Manages offline-first operations: connectivity, models, docs."""

    def __init__(self, provider: LLMProviderProtocol) -> None:
        self._provider = provider
        self._is_online: bool | None = None

    async def check_connectivity(self) -> bool:
        """Check if the LLM provider is reachable."""
        try:
            result = await self._provider.health_check()
            self._is_online = result
        except Exception:
            self._is_online = False
        return self._is_online

    async def list_local_models(
        self,
    ) -> list[str]:  # pragma: no cover — requires ollama binary installed
        """List locally available Ollama models via CLI."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama",
                "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []
            lines = stdout.decode().strip().splitlines()
            # Skip header line, extract model names (first column)
            models: list[str] = []
            for line in lines[1:]:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
        except (FileNotFoundError, OSError):
            logger.warning("ollama CLI not found")
            return []

    async def pull_model(
        self, model_name: str
    ) -> bool:  # pragma: no cover — requires ollama binary installed
        """Pull a model from Ollama registry (requires connectivity)."""
        if not await self.check_connectivity():
            logger.warning("Cannot pull model: no connectivity")
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama",
                "pull",
                model_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await proc.communicate()
            return proc.returncode == 0
        except (FileNotFoundError, OSError):
            logger.warning("ollama CLI not found, cannot pull model")
            return False

    def get_help(self, topic: str) -> str | None:
        """Get offline documentation for a topic."""
        return _OFFLINE_DOCS.get(topic)

    @property
    def is_online(self) -> bool | None:
        """Last known connectivity status (None if never checked)."""
        return self._is_online
