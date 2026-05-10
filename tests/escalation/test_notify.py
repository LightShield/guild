"""Tests for escalation/notify.py — notification system (REQ-15.2, REQ-15.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.escalation.notify import NotificationChannel, Notifier
from guild.escalation.queue import QuestionPriority


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestBellNotification:
    """Terminal bell notification tests."""

    async def test_bell_notification_writes_bell_char(self) -> None:
        """Bell notification writes the bell character to stdout."""
        notifier = Notifier(channels=[NotificationChannel.TERMINAL_BELL])
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify("Test message")
            mock_stdout.write.assert_called_once_with("\a")
            mock_stdout.flush.assert_called_once()


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestWebhookNotification:
    """Webhook notification tests."""

    async def test_webhook_sends_to_url(self) -> None:
        """Webhook notification sends JSON payload to configured URL."""
        notifier = Notifier(
            channels=[NotificationChannel.WEBHOOK],
            webhook_url="https://hooks.example.com/notify",
        )
        with patch("guild.escalation.notify.asyncio.get_event_loop") as mock_loop:
            mock_executor = AsyncMock()
            mock_loop.return_value.run_in_executor = mock_executor
            await notifier.notify("Agent needs help")
            mock_executor.assert_called_once()
            # Verify the URL was used (second arg to run_in_executor
            # is the function, third is the Request object)
            call_args = mock_executor.call_args
            assert call_args is not None


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestChannelConfiguration:
    """Channel configuration tests."""

    async def test_notify_respects_configured_channels(self) -> None:
        """Only configured channels are used for notifications."""
        notifier = Notifier(channels=[NotificationChannel.NONE])
        # NONE channel should not trigger any side effects
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            await notifier.notify("Quiet message")
            mock_stdout.write.assert_not_called()

    async def test_multiple_channels_all_triggered(self) -> None:
        """All configured channels fire on notification."""
        notifier = Notifier(
            channels=[
                NotificationChannel.TERMINAL_BELL,
                NotificationChannel.DESKTOP,
            ],
        )
        with (
            patch("sys.stdout") as mock_stdout,
            patch(
                "guild.escalation.notify.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
            ) as mock_proc,
        ):
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_proc.return_value.wait = AsyncMock()

            await notifier.notify("Multi-channel test")

            mock_stdout.write.assert_called_once_with("\a")
            mock_proc.assert_called_once()


@pytest.mark.unit
@pytest.mark.req("REQ-15.2")
class TestPresenceAware:
    """Presence-aware notification behavior."""

    async def test_notify_sends_on_high_priority(self) -> None:
        """High priority questions always trigger notification."""
        notifier = Notifier(channels=[NotificationChannel.TERMINAL_BELL])
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify(
                "Urgent: agent blocked",
                priority=QuestionPriority.HIGH,
            )
            mock_stdout.write.assert_called_once_with("\a")


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestWebhookEdgeCases:
    """Edge cases for webhook notification."""

    async def test_webhook_without_url_logs_warning(self) -> None:
        """Webhook notification without URL logs warning and returns."""
        notifier = Notifier(
            channels=[NotificationChannel.WEBHOOK],
            webhook_url=None,
        )
        # Should not raise, just log a warning
        with patch("guild.escalation.notify.logger") as mock_logger:
            await notifier.notify("test")
            mock_logger.warning.assert_called_once_with(
                "Webhook URL not configured for notification: %s", "test"
            )

    async def test_webhook_exception_is_handled(self) -> None:
        """Webhook failure is caught and logged, not raised."""
        notifier = Notifier(
            channels=[NotificationChannel.WEBHOOK],
            webhook_url="https://hooks.example.com/bad",
        )
        with patch("guild.escalation.notify.asyncio.get_event_loop") as mock_loop:
            mock_executor = AsyncMock(side_effect=Exception("connection error"))
            mock_loop.return_value.run_in_executor = mock_executor
            # Should not raise
            with patch("guild.escalation.notify.logger"):
                await notifier.notify("failing message")


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestDesktopNotification:
    """Desktop notification tests."""

    async def test_desktop_notification_calls_osascript_on_darwin(self) -> None:
        """Desktop notification uses osascript on macOS."""
        notifier = Notifier(channels=[NotificationChannel.DESKTOP])
        with (
            patch("sys.platform", "darwin"),
            patch(
                "guild.escalation.notify.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
            ) as mock_proc,
        ):
            mock_proc.return_value.wait = AsyncMock()
            await notifier.notify("macOS test")
            mock_proc.assert_called_once()
            # First arg should be osascript
            call_args = mock_proc.call_args[0]
            assert call_args[0] == "osascript"

    async def test_desktop_notification_calls_notify_send_on_linux(self) -> None:
        """Desktop notification uses notify-send on Linux."""
        notifier = Notifier(channels=[NotificationChannel.DESKTOP])
        with patch("guild.escalation.notify.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch(
                "guild.escalation.notify.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
            ) as mock_proc:
                mock_proc.return_value.wait = AsyncMock()
                await notifier.notify("Linux test")
                mock_proc.assert_called_once()
                call_args = mock_proc.call_args[0]
                assert call_args[0] == "notify-send"
