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
@pytest.mark.req("REQ-24.1")
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


@pytest.mark.unit
@pytest.mark.req("REQ-24.2")
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
@pytest.mark.req("REQ-24.3")
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
@pytest.mark.req("REQ-24.4")
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


@pytest.mark.unit
@pytest.mark.req("REQ-24.5")
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


@pytest.mark.unit
@pytest.mark.req("REQ-24.9")
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
@pytest.mark.req("REQ-24.10")
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
