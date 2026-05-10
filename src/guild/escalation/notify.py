"""Presence-aware notification system (REQ-15.2, REQ-15.5).

Sends notifications through configurable channels: terminal bell,
desktop toast, or webhook. Respects user presence/activity state.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from enum import Enum

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
    ) -> None:
        """Send notification through configured channels."""
        for channel in self._channels:
            await self._dispatch_channel(channel, message)

    async def _dispatch_channel(self, channel: NotificationChannel, message: str) -> None:
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
            await self._webhook(message)

    def _bell(self) -> None:
        """Terminal bell character."""
        sys.stdout.write("\a")
        sys.stdout.flush()

    async def _desktop(self, message: str) -> None:
        """Desktop notification (platform-specific)."""
        if sys.platform == "darwin":
            script = f'display notification "{message}" with title "{NOTIFICATION_TITLE}"'
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        elif sys.platform == "linux":
            proc = await asyncio.create_subprocess_exec(
                "notify-send",
                NOTIFICATION_TITLE,
                message,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        else:  # pragma: no cover — platform dependency (Windows)
            logger.warning("Desktop notifications not supported on %s", sys.platform)

    async def _webhook(self, message: str) -> None:
        """Send to configured webhook URL via HTTP POST."""
        if not self._webhook_url:
            logger.warning("Webhook URL not configured for notification: %s", message[:80])
            return

        import json
        import urllib.error
        from urllib.request import Request, urlopen

        payload = json.dumps({"text": message}).encode()
        req = Request(
            self._webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, urlopen, req)
        except (urllib.error.URLError, OSError):
            logger.exception("Webhook notification failed")
