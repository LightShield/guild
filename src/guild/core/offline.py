"""Offline-first features — local model management, graceful degradation (REQ-21)."""

from __future__ import annotations

import logging

from guild.core.models import ProviderConfig
from guild.providers.base import LLMProvider

__all__ = ["OfflineManager"]

log = logging.getLogger(__name__)


class OfflineManager:
    """Manages offline-first behavior and local model operations.

    Args:
        provider: The LLM provider to manage.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._is_online: bool | None = None

    async def check_connectivity(self) -> bool:
        """Check if the provider is reachable.

        Returns:
            True if online.
        """
        self._is_online = await self._provider.health_check()
        return self._is_online

    @property
    def is_online(self) -> bool | None:
        """Last known connectivity status (None if never checked)."""
        return self._is_online

    async def list_local_models(self) -> list[str]:
        """List locally available models.

        Returns:
            List of model names, or empty list if offline.
        """
        try:
            return await self._provider.list_models()
        except Exception:
            log.warning("Cannot list models — provider unreachable")
            return []
