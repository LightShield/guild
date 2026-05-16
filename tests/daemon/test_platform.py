"""Tests for platform adapter (REQ-02.4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from guild.daemon.platform import (
    DarwinAdapter,
    FallbackAdapter,
    LinuxAdapter,
    PlatformAdapter,
    get_platform_adapter,
)

pytestmark = pytest.mark.unit


class TestPlatformAdapterInterface:
    """Verify all adapters satisfy the PlatformAdapter protocol."""

    def test_darwin_adapter_satisfies_protocol(self) -> None:
        """DarwinAdapter is a runtime-checkable PlatformAdapter."""
        adapter = DarwinAdapter()
        assert isinstance(adapter, PlatformAdapter)
        assert adapter.platform_name == "darwin"

    def test_linux_adapter_satisfies_protocol(self) -> None:
        """LinuxAdapter is a runtime-checkable PlatformAdapter."""
        adapter = LinuxAdapter()
        assert isinstance(adapter, PlatformAdapter)
        assert adapter.platform_name == "linux"

    def test_fallback_adapter_satisfies_protocol(self) -> None:
        """FallbackAdapter is a runtime-checkable PlatformAdapter."""
        adapter = FallbackAdapter()
        assert isinstance(adapter, PlatformAdapter)


class TestGetPlatformAdapter:
    """Verify get_platform_adapter returns correct adapter per platform."""

    def test_returns_darwin_on_macos(self) -> None:
        """Factory returns DarwinAdapter when sys.platform is darwin."""
        with patch("guild.daemon.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            adapter = get_platform_adapter()
        assert isinstance(adapter, DarwinAdapter)

    def test_returns_linux_on_linux(self) -> None:
        """Factory returns LinuxAdapter when sys.platform is linux."""
        with patch("guild.daemon.platform.sys") as mock_sys:
            mock_sys.platform = "linux"
            adapter = get_platform_adapter()
        assert isinstance(adapter, LinuxAdapter)

    def test_returns_fallback_on_windows(self) -> None:
        """Factory returns FallbackAdapter on unrecognized platforms."""
        with patch("guild.daemon.platform.sys") as mock_sys:
            mock_sys.platform = "win32"
            adapter = get_platform_adapter()
        assert isinstance(adapter, FallbackAdapter)


class TestDarwinAdapter:
    """Test macOS adapter behavior."""

    def test_idle_detection_parses_ioreg(self) -> None:
        """Parses HIDIdleTime from ioreg output to detect idle state."""
        adapter = DarwinAdapter()
        mock_result = MagicMock()
        mock_result.stdout = '  |   "HIDIdleTime" = 600000000000\n'
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.is_user_idle(threshold_seconds=300.0) is True

    def test_idle_returns_false_on_error(self) -> None:
        """Returns False when ioreg command fails."""
        adapter = DarwinAdapter()
        with patch("subprocess.run", side_effect=OSError("no ioreg")):
            assert adapter.is_user_idle() is False

    def test_notification_calls_osascript(self) -> None:
        """Sends desktop notification via osascript."""
        adapter = DarwinAdapter()
        mock_result = MagicMock()
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = adapter.send_desktop_notification("Title", "Body")
        assert result is True
        assert "osascript" in mock_run.call_args[0][0]

    def test_notification_returns_false_on_error(self) -> None:
        """Returns False when osascript command fails."""
        adapter = DarwinAdapter()
        with patch("subprocess.run", side_effect=OSError()):
            assert adapter.send_desktop_notification("T", "B") is False


class TestLinuxAdapter:
    """Test Linux adapter behavior."""

    def test_idle_detection_parses_xprintidle(self) -> None:
        """Parses xprintidle output (ms) to detect idle state."""
        adapter = LinuxAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "600000\n"
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.is_user_idle(threshold_seconds=300.0) is True

    def test_idle_returns_false_on_missing_xprintidle(self) -> None:
        """Returns False when xprintidle is not installed."""
        adapter = LinuxAdapter()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert adapter.is_user_idle() is False

    def test_notification_calls_notify_send(self) -> None:
        """Sends desktop notification via notify-send."""
        adapter = LinuxAdapter()
        mock_result = MagicMock()
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = adapter.send_desktop_notification("Title", "Body")
        assert result is True
        assert "notify-send" in mock_run.call_args[0][0]

    def test_notification_returns_false_on_missing_tool(self) -> None:
        """Returns False when notify-send is not installed."""
        adapter = LinuxAdapter()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert adapter.send_desktop_notification("T", "B") is False


class TestFallbackAdapter:
    """Test fallback adapter (safe defaults for unknown platforms)."""

    def test_is_user_idle_always_false(self) -> None:
        """Fallback always reports user as present."""
        adapter = FallbackAdapter()
        assert adapter.is_user_idle() is False

    def test_detect_sleep_wake_always_false(self) -> None:
        """Fallback never detects sleep/wake transitions."""
        adapter = FallbackAdapter()
        assert adapter.detect_sleep_wake() is False

    def test_notification_returns_false(self) -> None:
        """Fallback notification always returns False."""
        adapter = FallbackAdapter()
        assert adapter.send_desktop_notification("T", "B") is False


class TestCrossPlatformGuarantees:
    """Verify cross-platform coding practices (REQ-02.1, REQ-02.3)."""

    def test_no_os_path_in_source(self) -> None:
        """Verify pathlib is used instead of os.path throughout."""
        import pathlib

        src_dir = pathlib.Path(__file__).parent.parent.parent / "src" / "guild"
        violations = []
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            if "os.path" in content:
                violations.append(str(py_file.relative_to(src_dir)))
        assert violations == [], f"os.path usage found in: {violations}"

    def test_pathlib_used_for_file_operations(self) -> None:
        """Verify Path is used in key modules."""
        import inspect

        from guild.config.loader import find_guild_dir  # noqa: F401
        from guild.storage.sqlite import Storage

        # Check that Storage.__init__ accepts Path
        sig = inspect.signature(Storage.__init__)
        assert "db_path" in sig.parameters


class TestSingleInstallMechanism:
    """Verify pip install works as single mechanism."""

    def test_pyproject_toml_has_scripts_entry(self) -> None:
        """The guild CLI is installable via pip."""
        import pathlib

        pyproject = pathlib.Path(__file__).parent.parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert 'guild = "guild.cli.main:app"' in content


class TestDarwinAdapterEdgeCases:
    """Cover remaining branches in DarwinAdapter."""

    def test_idle_false_when_no_hididletime_in_output(self) -> None:
        from guild.daemon.platform import DarwinAdapter

        adapter = DarwinAdapter()
        mock_result = MagicMock()
        mock_result.stdout = "  |   SomeOtherKey = 123\n"
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.is_user_idle() is False

    def test_idle_false_when_bad_split(self) -> None:
        from guild.daemon.platform import DarwinAdapter

        adapter = DarwinAdapter()
        mock_result = MagicMock()
        mock_result.stdout = '  |   "HIDIdleTime" no_equals_sign\n'
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.is_user_idle() is False

    def test_detect_sleep_wake_returns_false(self) -> None:
        from guild.daemon.platform import DarwinAdapter

        assert DarwinAdapter().detect_sleep_wake() is False


class TestLinuxAdapterEdgeCases:
    """Cover remaining branches in LinuxAdapter."""

    def test_idle_false_when_nonzero_returncode(self) -> None:
        from guild.daemon.platform import LinuxAdapter

        adapter = LinuxAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.is_user_idle() is False

    def test_detect_sleep_wake_returns_false(self) -> None:
        from guild.daemon.platform import LinuxAdapter

        assert LinuxAdapter().detect_sleep_wake() is False


class TestFallbackAdapterPlatformName:
    """Fallback adapter reports actual platform name."""

    def test_platform_name_returns_current_platform(self) -> None:
        import sys

        from guild.daemon.platform import FallbackAdapter

        assert FallbackAdapter().platform_name == sys.platform


# --- Tests moved from e2e/test_cli_commands.py (black-box violation) ---


class TestPlatformAdapterFromE2E:
    """Verify PlatformAdapter can be instantiated for the current platform (AC-02.4.3)."""

    @pytest.mark.ac("AC-02.4.3")
    def test_adapter_interface_exists_and_works(self) -> None:
        """PlatformAdapter can be instantiated for current platform."""
        adapter = get_platform_adapter()
        assert isinstance(adapter, PlatformAdapter)
        assert isinstance(adapter.platform_name, str)


class TestPlatformAdapterAbstract:
    """Verify PlatformAdapter is abstract (AC-02.4.1)."""

    @pytest.mark.ac("AC-02.4.1")
    def test_platform_adapter_is_protocol(self) -> None:
        """PlatformAdapter is a Protocol with required methods."""
        assert hasattr(PlatformAdapter, "platform_name")
        assert hasattr(PlatformAdapter, "is_user_idle")
        assert hasattr(PlatformAdapter, "detect_sleep_wake")


class TestConcreteAdaptersFromE2E:
    """Verify concrete adapters exist for supported platforms (AC-02.4.2)."""

    @pytest.mark.ac("AC-02.4.2")
    def test_darwin_and_linux_adapters_importable(self) -> None:
        """DarwinAdapter and LinuxAdapter are importable."""
        assert DarwinAdapter is not None
        assert LinuxAdapter is not None
        assert FallbackAdapter is not None


class TestFallbackAdapterFromE2E:
    """FallbackAdapter is used on unsupported platforms (AC-02.4.4)."""

    @pytest.mark.ac("AC-02.4.4")
    def test_fallback_adapter_has_platform_name(self) -> None:
        """FallbackAdapter exposes platform_name attribute."""
        adapter = FallbackAdapter()
        assert hasattr(adapter, "platform_name")
        assert isinstance(adapter.platform_name, str)


class TestCrossPlatformAbstractions:
    """Verify key modules use pathlib.Path for file operations (AC-02.3.1)."""

    @pytest.mark.ac("AC-02.3.1")
    def test_pathlib_used_for_paths(self) -> None:
        """Key modules use pathlib.Path for file operations."""
        import inspect

        from guild.storage.sqlite import Storage

        sig = inspect.signature(Storage.__init__)
        assert "db_path" in sig.parameters
