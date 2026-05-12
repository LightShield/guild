"""Tests for daemon/resource.py — resource-aware scheduling (REQ-24)."""

from __future__ import annotations

import asyncio

import pytest

from guild.daemon.resource import (
    ActivityState,
    ResourceMonitor,
    ResourceThresholds,
    SchedulingMode,
)


@pytest.mark.unit
class TestIdleDetection:
    """User activity state detection."""

    def test_idle_detection_returns_idle_when_no_activity(self) -> None:
        """When CPU is below threshold, user is considered idle."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 10.0,
        )
        assert monitor.detect_activity() == ActivityState.IDLE

    def test_idle_detection_returns_active_when_recent_activity(self) -> None:
        """When CPU is above threshold, user is considered active."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 90.0,
        )
        assert monitor.detect_activity() == ActivityState.ACTIVE

    def test_idle_when_cpu_below_threshold(self) -> None:
        """Activity detector reporting IDLE when CPU is below threshold."""
        # Edge case: CPU is exactly at the threshold boundary (below)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 79.9,  # Just below default 80% threshold
        )
        assert monitor.detect_activity() == ActivityState.IDLE
        # Verify CPU reading is coherent with idle state
        assert monitor.get_cpu_percent() < 80.0


@pytest.mark.unit
class TestCpuLoadDetection:
    """System load detection."""

    def test_cpu_load_detection(self) -> None:
        """CPU reader returns current utilization percentage."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.FULL,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 42.5,
        )
        assert monitor.get_cpu_percent() == 42.5


@pytest.mark.unit
class TestSchedulingModes:
    """Three scheduling modes: full, polite, stealth."""

    async def test_full_mode_never_throttles(self) -> None:
        """Full mode returns immediately regardless of activity."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.FULL,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 95.0,
        )
        # Should return immediately, no delay
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.1

    async def test_polite_mode_throttles_when_active(self) -> None:
        """Polite mode delays when user is active."""
        thresholds = ResourceThresholds(polite_delay_seconds=0.1)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 90.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.09  # Allow small timing variance

    async def test_stealth_mode_pauses_when_active(self) -> None:
        """Stealth mode blocks until user becomes idle."""
        call_count = 0

        def toggling_detector() -> ActivityState:
            nonlocal call_count
            call_count += 1
            # First two calls return ACTIVE, third returns IDLE
            if call_count <= 2:
                return ActivityState.ACTIVE
            return ActivityState.IDLE

        thresholds = ResourceThresholds(poll_interval_seconds=0.05)
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=thresholds,
            activity_detector=toggling_detector,
            cpu_reader=lambda: 50.0,
        )
        await monitor.wait_if_throttled()
        # Should have polled multiple times before getting IDLE
        assert call_count >= 2


@pytest.mark.unit
class TestPoliteDelay:
    """Polite mode delay is configurable."""

    async def test_polite_delay_configurable(self) -> None:
        """Different polite_delay_seconds values produce different wait times."""
        thresholds = ResourceThresholds(polite_delay_seconds=0.15)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 90.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.14
        assert elapsed < 0.3

    async def test_polite_does_not_delay_when_idle(self) -> None:
        """Polite mode skips the delay when user is idle."""
        thresholds = ResourceThresholds(polite_delay_seconds=5.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 10.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start
        # Should return immediately (no 5s delay)
        assert elapsed < 0.1

    async def test_polite_delay_is_configurable_seconds(self) -> None:
        """Polite delay duration matches the configured polite_delay_seconds value."""
        thresholds = ResourceThresholds(polite_delay_seconds=0.2)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 95.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start
        # Should be approximately 0.2s
        assert elapsed >= 0.19
        assert elapsed < 0.35


@pytest.mark.unit
class TestStealthWait:
    """Stealth mode waits for idle."""

    async def test_stealth_waits_for_idle(self) -> None:
        """Stealth blocks until activity_detector returns IDLE."""
        calls: list[int] = []

        def counting_detector() -> ActivityState:
            calls.append(1)
            if len(calls) >= 4:
                return ActivityState.IDLE
            return ActivityState.ACTIVE

        thresholds = ResourceThresholds(poll_interval_seconds=0.02)
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=thresholds,
            activity_detector=counting_detector,
            cpu_reader=lambda: 50.0,
        )
        await monitor.wait_if_throttled()
        assert len(calls) >= 4

    async def test_stealth_resumes_when_idle_detected(self) -> None:
        """Stealth mode unblocks immediately once idle is detected."""
        call_count = 0

        def detector_becomes_idle() -> ActivityState:
            nonlocal call_count
            call_count += 1
            # Active for 2 polls, then idle
            if call_count <= 2:
                return ActivityState.ACTIVE
            return ActivityState.IDLE

        thresholds = ResourceThresholds(poll_interval_seconds=0.02)
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=thresholds,
            activity_detector=detector_becomes_idle,
            cpu_reader=lambda: 50.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start

        # Should have taken approximately 2 poll intervals (2 * 0.02 = 0.04s)
        assert elapsed < 0.2
        # Once idle was detected, it unblocked
        assert call_count >= 3

    async def test_stealth_blocks_when_active(self) -> None:
        """Stealth mode blocks execution while user is active."""
        polls: list[float] = []

        def always_active_then_idle() -> ActivityState:
            polls.append(asyncio.get_event_loop().time())
            # Active for 5 polls, then idle
            if len(polls) <= 5:
                return ActivityState.ACTIVE
            return ActivityState.IDLE

        thresholds = ResourceThresholds(poll_interval_seconds=0.02)
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=thresholds,
            activity_detector=always_active_then_idle,
            cpu_reader=lambda: 85.0,
        )
        start = asyncio.get_event_loop().time()
        await monitor.wait_if_throttled()
        elapsed = asyncio.get_event_loop().time() - start

        # Should have been blocked for at least 5 * 0.02 = 0.1s
        assert elapsed >= 0.08
        assert len(polls) >= 5


@pytest.mark.unit
class TestThresholds:
    """Threshold configuration."""

    def test_thresholds_configurable(self) -> None:
        """All threshold values can be overridden."""
        thresholds = ResourceThresholds(
            idle_timeout_seconds=120.0,
            cpu_threshold_percent=50.0,
            polite_delay_seconds=5.0,
            poll_interval_seconds=10.0,
        )
        assert thresholds.idle_timeout_seconds == 120.0
        assert thresholds.cpu_threshold_percent == 50.0
        assert thresholds.polite_delay_seconds == 5.0
        assert thresholds.poll_interval_seconds == 10.0

    def test_default_thresholds(self) -> None:
        """Default threshold values are sensible."""
        thresholds = ResourceThresholds()
        assert thresholds.idle_timeout_seconds == 300.0
        assert thresholds.cpu_threshold_percent == 80.0
        assert thresholds.polite_delay_seconds == 10.0
        assert thresholds.poll_interval_seconds == 5.0


@pytest.mark.unit
class TestGetStatus:
    """ResourceMonitor.get_status() returns full status snapshot."""

    def test_get_status_returns_throttled_when_active_polite(self) -> None:
        """get_status reports throttled=True in polite mode with active user."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 85.0,
        )
        status = monitor.get_status()
        assert status.mode == SchedulingMode.POLITE
        assert status.activity == ActivityState.ACTIVE
        assert status.cpu_percent == 85.0
        assert status.is_throttled is True
        assert "polite" in status.reason.lower()

    def test_get_status_returns_not_throttled_when_idle(self) -> None:
        """get_status reports throttled=False in polite mode with idle user."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 20.0,
        )
        status = monitor.get_status()
        assert status.is_throttled is False
        assert status.reason == ""

    def test_get_status_stealth_active_gives_paused_reason(self) -> None:
        """get_status reports 'paused until idle' reason in stealth mode."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 75.0,
        )
        status = monitor.get_status()
        assert status.is_throttled is True
        assert "paused" in status.reason.lower()

    def test_get_status_full_mode_never_throttled(self) -> None:
        """get_status reports throttled=False in full mode regardless."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.FULL,
            activity_detector=lambda: ActivityState.ACTIVE,
            cpu_reader=lambda: 99.0,
        )
        status = monitor.get_status()
        assert status.is_throttled is False
        assert status.reason == ""


@pytest.mark.unit
class TestMonitorPolling:
    """Resource monitor polling interval."""

    async def test_monitor_polling_interval(self) -> None:
        """Stealth mode polls at the configured interval."""
        timestamps: list[float] = []
        call_count = 0

        def timed_detector() -> ActivityState:
            nonlocal call_count
            call_count += 1
            timestamps.append(asyncio.get_event_loop().time())
            if call_count >= 3:
                return ActivityState.IDLE
            return ActivityState.ACTIVE

        thresholds = ResourceThresholds(poll_interval_seconds=0.05)
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=thresholds,
            activity_detector=timed_detector,
            cpu_reader=lambda: 50.0,
        )
        await monitor.wait_if_throttled()
        # At least 2 intervals should have elapsed
        assert len(timestamps) >= 3
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            # Each gap should be approximately poll_interval_seconds
            assert gap >= 0.04  # Allow timing variance


def _gpu_high() -> dict[str, object]:
    return {"gpu_percent": 90.0, "vram_used_mb": 7000, "vram_total_mb": 8192}


def _gpu_over_threshold() -> dict[str, object]:
    return {"gpu_percent": 50.0, "vram_used_mb": 7500, "vram_total_mb": 8192}


def _gpu_under_threshold() -> dict[str, object]:
    return {"gpu_percent": 30.0, "vram_used_mb": 2000, "vram_total_mb": 8192}


def _gpu_mid() -> dict[str, object]:
    return {"gpu_percent": 45.0, "vram_used_mb": 4000, "vram_total_mb": 8192}


def _thermal_throttled_hot() -> dict[str, object]:
    return {"is_throttled": True, "cpu_temp_celsius": 95.0}


def _thermal_throttled_critical() -> dict[str, object]:
    return {"is_throttled": True, "cpu_temp_celsius": 98.0}


def _thermal_ok_warm() -> dict[str, object]:
    return {"is_throttled": False, "cpu_temp_celsius": 60.0}


def _thermal_ok_cool() -> dict[str, object]:
    return {"is_throttled": False, "cpu_temp_celsius": 55.0}


@pytest.mark.unit
class TestGpuVramAwareness:
    """ResourceMonitor detects GPU/VRAM pressure and throttles."""

    def test_gpu_reader_injected(self) -> None:
        """ResourceMonitor accepts a gpu_reader callable."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE, gpu_reader=_gpu_high,
        )
        expected = {
            "gpu_percent": 90.0,
            "vram_used_mb": 7000,
            "vram_total_mb": 8192,
        }
        assert monitor.get_gpu_status() == expected

    def test_high_vram_triggers_throttle(self) -> None:
        """When VRAM usage > threshold, monitor recommends deferring."""
        from guild.daemon.resource import (
            ResourceMonitor,
            ResourceThresholds,
            SchedulingMode,
        )

        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            gpu_reader=_gpu_over_threshold,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "vram" in status.reason.lower()

    def test_low_vram_no_throttle(self) -> None:
        """When VRAM is below threshold, no GPU-based throttling."""
        from guild.daemon.resource import (
            ResourceMonitor,
            ResourceThresholds,
            SchedulingMode,
        )

        thresholds = ResourceThresholds(vram_pressure_percent=85.0)
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thresholds=thresholds,
            gpu_reader=_gpu_under_threshold,
        )
        status = monitor.get_status()
        assert not status.is_throttled

    def test_no_gpu_reader_returns_none(self) -> None:
        """Without a gpu_reader, get_gpu_status returns None."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(mode=SchedulingMode.POLITE)
        assert monitor.get_gpu_status() is None

    def test_gpu_status_in_resource_status(self) -> None:
        """ResourceStatus includes gpu_status field."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE, gpu_reader=_gpu_mid,
        )
        status = monitor.get_status()
        assert status.gpu_status is not None
        assert status.gpu_status["gpu_percent"] == 45.0


@pytest.mark.unit
class TestThermalAwareness:
    """ResourceMonitor detects thermal throttling and reduces rate."""

    def test_thermal_reader_injected(self) -> None:
        """ResourceMonitor accepts a thermal_reader callable."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thermal_reader=_thermal_throttled_hot,
        )
        expected = {"is_throttled": True, "cpu_temp_celsius": 95.0}
        assert monitor.get_thermal_status() == expected

    def test_thermal_throttle_triggers_polite_delay(self) -> None:
        """When thermal throttling detected, monitor is throttled."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thermal_reader=_thermal_throttled_critical,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "thermal" in status.reason.lower()

    def test_no_thermal_throttle_no_delay(self) -> None:
        """When thermal is fine, no thermal-based throttling."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thermal_reader=_thermal_ok_warm,
        )
        status = monitor.get_status()
        assert not status.is_throttled

    def test_no_thermal_reader_returns_none(self) -> None:
        """Without a thermal_reader, get_thermal_status returns None."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(mode=SchedulingMode.POLITE)
        assert monitor.get_thermal_status() is None

    def test_thermal_status_in_resource_status(self) -> None:
        """ResourceStatus includes thermal_status field."""
        from guild.daemon.resource import ResourceMonitor, SchedulingMode

        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            thermal_reader=_thermal_ok_cool,
        )
        status = monitor.get_status()
        assert status.thermal_status is not None
        assert status.thermal_status["cpu_temp_celsius"] == 55.0


@pytest.mark.unit
class TestGpuVramEdgeCases:
    """Cover remaining branches in GPU/VRAM logic."""

    def test_vram_total_zero_no_throttle(self) -> None:
        """VRAM total of 0 doesn't divide-by-zero, returns no throttle."""
        gpu_reader = lambda: {"gpu_percent": 50.0, "vram_used_mb": 100, "vram_total_mb": 0}
        monitor = ResourceMonitor(
            mode=SchedulingMode.POLITE,
            gpu_reader=gpu_reader,
            activity_detector=lambda: ActivityState.ACTIVE,
        )
        status = monitor.get_status()
        assert not status.is_throttled or "vram" not in status.reason.lower()

    def test_stealth_mode_with_vram_pressure_shows_vram_reason(self) -> None:
        """In STEALTH mode with VRAM pressure, reason includes VRAM."""
        gpu_reader = lambda: {"gpu_percent": 90.0, "vram_used_mb": 7500, "vram_total_mb": 8192}
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            gpu_reader=gpu_reader,
            activity_detector=lambda: ActivityState.ACTIVE,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "vram" in status.reason.lower()

    def test_stealth_no_gpu_or_thermal_shows_stealth_reason(self) -> None:
        """STEALTH mode without GPU/thermal pressure shows user-active reason."""
        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=lambda: ActivityState.ACTIVE,
        )
        status = monitor.get_status()
        assert status.is_throttled
        assert "paused until idle" in status.reason.lower()


# ======================================================================
# Resource monitor stealth mode (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestResourceMonitorStealthExit:
    """ResourceMonitor stealth mode exits when user becomes idle."""

    async def test_stealth_mode_exits_on_idle(self) -> None:
        """Stealth mode blocks while active and unblocks when idle."""
        call_count = 0

        def detector() -> ActivityState:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return ActivityState.ACTIVE
            return ActivityState.IDLE

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=detector,
            cpu_reader=lambda: 20.0,
        )
        monitor.thresholds.poll_interval_seconds = 0.01
        await monitor.wait_if_throttled()
        # Should have polled at least twice (once ACTIVE, once IDLE)
        assert call_count >= 2


# ======================================================================
# Resource throttle STEALTH exit branch (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestResourceThrottleStealthExit:
    """Cover the STEALTH mode exit branch in wait_if_throttled."""

    async def test_stealth_mode_returns_when_idle(self) -> None:
        """In STEALTH mode, if user is idle, returns immediately (exit branch)."""
        import time

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 10.0,
        )

        # Should return immediately since user is IDLE
        start = time.monotonic()
        await monitor.wait_if_throttled()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    async def test_stealth_mode_blocks_then_releases(self) -> None:
        """In STEALTH mode, blocks while active then proceeds when idle."""
        call_count = 0

        def activity_changes() -> ActivityState:
            nonlocal call_count
            call_count += 1
            # First call: ACTIVE, second call: IDLE (unblocks)
            return ActivityState.ACTIVE if call_count <= 1 else ActivityState.IDLE

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=ResourceThresholds(poll_interval_seconds=0.01),
            activity_detector=activity_changes,
            cpu_reader=lambda: 10.0,
        )

        await monitor.wait_if_throttled()
        # Should have polled at least twice
        assert call_count >= 2
