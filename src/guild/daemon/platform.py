"""Platform-specific adapters for idle detection, sleep detection, and notifications.

Isolates all platform-dependent behavior behind a common interface (REQ-02.4).
"""

from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable

from guild.config.constants import DEFAULT_IDLE_THRESHOLD_SECONDS, PLATFORM_SUBPROCESS_TIMEOUT
from logger_python import get_logger

__all__ = [
    "PlatformAdapter",
    "get_platform_adapter",
    "DarwinAdapter",
    "LinuxAdapter",
    "FallbackAdapter",
]

logger = get_logger(__name__)


@runtime_checkable
class PlatformAdapter(Protocol):
    """Interface for platform-specific operations."""

    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        ...

    def is_user_idle(self, threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS) -> bool:
        """Check if the user has been idle for at least threshold_seconds."""
        ...

    def detect_sleep_wake(self) -> bool:
        """Return True if a sleep/wake transition was recently detected."""
        ...

    def send_desktop_notification(self, title: str, message: str) -> bool:
        """Send a desktop notification. Returns True on success."""
        ...


class DarwinAdapter:
    """macOS platform adapter using IOKit for idle detection."""

    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        return "darwin"

    def is_user_idle(self, threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS) -> bool:
        """Check user idle time via ioreg HIDIdleTime (nanoseconds)."""
        try:
            import subprocess

            result = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True,
                text=True,
                timeout=PLATFORM_SUBPROCESS_TIMEOUT,
            )
            for line in result.stdout.splitlines():
                if "HIDIdleTime" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        idle_ns = int(parts[1].strip())
                        return idle_ns / 1_000_000_000 >= threshold_seconds
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return False

    def detect_sleep_wake(self) -> bool:
        """Detect sleep/wake via IOPowerManagement (stub)."""
        # macOS sleep/wake detection would use IOPowerManagement
        # Simplified: check system uptime delta
        return False

    def send_desktop_notification(self, title: str, message: str) -> bool:
        """Send notification via osascript on macOS."""
        try:
            import subprocess

            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "{title}"',
                ],
                capture_output=True,
                timeout=PLATFORM_SUBPROCESS_TIMEOUT,
            )
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False


class LinuxAdapter:
    """Linux platform adapter using xprintidle for idle detection."""

    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        return "linux"

    def is_user_idle(self, threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS) -> bool:
        """Check user idle time via xprintidle (milliseconds)."""
        try:
            import subprocess

            result = subprocess.run(
                ["xprintidle"],
                capture_output=True,
                text=True,
                timeout=PLATFORM_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0:
                idle_ms = int(result.stdout.strip())
                return idle_ms / 1000 >= threshold_seconds
        except (OSError, ValueError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    def detect_sleep_wake(self) -> bool:
        """Detect sleep/wake on Linux (stub)."""
        return False

    def send_desktop_notification(self, title: str, message: str) -> bool:
        """Send notification via notify-send on Linux."""
        try:
            import subprocess

            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=PLATFORM_SUBPROCESS_TIMEOUT,
            )
            return True
        except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
            return False


class FallbackAdapter:
    """Fallback adapter for unsupported platforms (always returns safe defaults)."""

    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        return sys.platform

    def is_user_idle(self, threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS) -> bool:
        """Always returns False (assume user is present)."""
        return False

    def detect_sleep_wake(self) -> bool:
        """Always returns False (no sleep/wake detection available)."""
        return False

    def send_desktop_notification(self, title: str, message: str) -> bool:
        """Log a debug message and return False (notifications unavailable)."""
        logger.debug("Desktop notifications not available on %s", sys.platform)
        return False


def get_platform_adapter() -> PlatformAdapter:
    """Return the appropriate adapter for the current platform."""
    if sys.platform == "darwin":
        return DarwinAdapter()
    elif sys.platform == "linux":
        return LinuxAdapter()
    return FallbackAdapter()
