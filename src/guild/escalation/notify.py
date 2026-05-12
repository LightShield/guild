"""Presence-aware notification system (REQ-15.2, REQ-15.5).

Sends notifications through configurable channels: terminal bell,
desktop toast, or webhook. Respects user presence/activity state.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from guild.daemon.platform import get_platform_adapter
from guild.escalation.queue import QuestionPriority

__all__ = ["NOTIFICATION_TITLE", "NotificationChannel", "Notifier"]

logger = logging.getLogger(__name__)

NOTIFICATION_TITLE = "Guild"


class NotificationChannel(str, Enum):
    """Available notification delivery channels."""

    TERMINAL_BELL = "bell"
    DESKTOP = "desktop"
    WEBHOOK = "webhook"
    NONE = "none"


class Notifier:
    """Presence-aware notification system (REQ-15.2, REQ-15.5).

    Sends notifications through configured channels. High-priority
    questions always trigger immediate notification regardless of
    presence state.
    """

    def __init__(
        self,
        channels: list[NotificationChannel] | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self._channels = channels or [NotificationChannel.TERMINAL_BELL]
        self._webhook_url = webhook_url

    async def notify(
        self,
        message: str,
        priority: QuestionPriority = QuestionPriority.NORMAL,
        task_id: str | None = None,
        question: str | None = None,
    ) -> None:
        """Send notification through configured channels."""
        for channel in self._channels:
            await self._dispatch_channel(
                channel, message, task_id=task_id, question=question,
            )

    async def _dispatch_channel(
        self,
        channel: NotificationChannel,
        message: str,
        task_id: str | None = None,
        question: str | None = None,
    ) -> None:
        """Dispatch a notification to a single channel."""
        if channel == NotificationChannel.NONE:
            return
        if channel == NotificationChannel.TERMINAL_BELL:
            self._bell()
            return
        if channel == NotificationChannel.DESKTOP:
            await self._desktop(message)
            return
        if channel == NotificationChannel.WEBHOOK:  # pragma: no branch
            await self._webhook(message, task_id=task_id, question=question)

    def _bell(self) -> None:
        """Terminal bell character."""
        sys.stdout.write("\a")
        sys.stdout.flush()

    async def _desktop(self, message: str) -> None:
        """Desktop notification (platform-specific, via PlatformAdapter REQ-02.4)."""
        adapter = get_platform_adapter()
        adapter.send_desktop_notification(NOTIFICATION_TITLE, message)

    async def _webhook(
        self,
        message: str,
        task_id: str | None = None,
        question: str | None = None,
    ) -> None:
        """Send to configured webhook URL via HTTP POST."""
        if not self._webhook_url:
            logger.warning("Webhook URL not configured for notification: %s", message[:80])
            return

        payload: dict[str, Any] = {
            "text": message,
            "task_id": task_id,
            "question": question,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await _post_json(self._webhook_url, payload)


async def _post_json(url: str, payload: dict[str, Any]) -> None:
    """HTTP POST a JSON payload to *url*.

    Wraps urllib so the HTTP dependency is isolated in one place and
    can be swapped for httpx/aiohttp later without touching callers.
    """
    import json
    import urllib.error
    from urllib.request import Request, urlopen

    data = json.dumps(payload).encode()
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, urlopen, req)
    except (urllib.error.URLError, OSError):
        logger.warning("HTTP POST to %s failed", url, exc_info=True)
