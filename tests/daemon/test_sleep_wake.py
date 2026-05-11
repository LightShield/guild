"""Tests for daemon/sleep_wake.py — sleep/wake survival (REQ-26)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector, WakeBehavior


@pytest.mark.unit
@pytest.mark.req("REQ-26.1")
class TestDetectsSleep:
    """Sleep detection via time-drift."""

    async def test_detects_sleep_via_time_drift(self) -> None:
        """Large time drift (> threshold) is detected as sleep."""
        detector = SleepWakeDetector(config=SleepWakeConfig(sleep_threshold_seconds=10.0))
        # Simulate: mark turn start at t=100, then check at t=200 (100s drift)
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=100.0):
            detector.mark_turn_start()

        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=200.0):
            assert detector.check_for_sleep() is True
            assert detector.sleep_detected is True

    async def test_no_false_positive_on_normal_delay(self) -> None:
        """Normal delay (< threshold) is not flagged as sleep."""
        detector = SleepWakeDetector(config=SleepWakeConfig(sleep_threshold_seconds=60.0))
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=100.0):
            detector.mark_turn_start()

        # 5 seconds later — well within threshold
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=105.0):
            assert detector.check_for_sleep() is False
            assert detector.sleep_detected is False

    async def test_no_false_positive_on_short_delay(self) -> None:
        """A delay just below threshold does NOT trigger sleep detection."""
        # Use a 30s threshold; delay of 29s should not trigger
        detector = SleepWakeDetector(config=SleepWakeConfig(sleep_threshold_seconds=30.0))
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=1000.0):
            detector.mark_turn_start()

        # 29 seconds later — just below threshold
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=1029.0):
            assert detector.check_for_sleep() is False
            assert detector.sleep_detected is False

        # But 31 seconds DOES trigger
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=1031.0):
            assert detector.check_for_sleep() is True
            assert detector.sleep_detected is True


@pytest.mark.unit
@pytest.mark.req("REQ-26.2")
class TestResumeAfterSleep:
    """Resume behavior after detected sleep."""

    async def test_resume_after_detected_sleep(self) -> None:
        """With RESUME behavior, should_resume returns True after sleep."""
        detector = SleepWakeDetector(config=SleepWakeConfig(wake_behavior=WakeBehavior.RESUME))
        # Simulate sleep detection
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=0.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=999.0):
            detector.check_for_sleep()

        assert detector.sleep_detected is True
        assert detector.should_resume() is True

    async def test_stay_paused_when_configured(self) -> None:
        """With STAY_PAUSED behavior, should_resume returns False after sleep."""
        detector = SleepWakeDetector(config=SleepWakeConfig(wake_behavior=WakeBehavior.STAY_PAUSED))
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=0.0):
            detector.mark_turn_start()
        with patch("guild.daemon.sleep_wake.time.monotonic", return_value=999.0):
            detector.check_for_sleep()

        assert detector.sleep_detected is True
        assert detector.should_resume() is False


@pytest.mark.unit
@pytest.mark.req("REQ-26.3")
class TestHealthCheckOnWake:
    """Ollama connection re-validated on wake."""

    async def test_health_check_called_after_wake(self) -> None:
        """Provider health_check is called during wake recovery."""
        detector = SleepWakeDetector(config=SleepWakeConfig(health_check_retries=3))
        provider = AsyncMock()
        provider.health_check.return_value = True

        result = await detector.wait_for_provider_recovery(provider)

        assert result is True
        provider.health_check.assert_called_once()

    async def test_retries_health_check_on_failure(self) -> None:
        """Health check retries until provider comes back online."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=4,
                health_check_retry_delay=0.01,
            )
        )
        provider = AsyncMock()
        # Fails twice, then succeeds
        provider.health_check.side_effect = [False, False, True]

        result = await detector.wait_for_provider_recovery(provider)

        assert result is True
        assert provider.health_check.call_count == 3


@pytest.mark.unit
@pytest.mark.req("REQ-26.4")
class TestRetryLLMCallAfterSleep:
    """In-flight LLM calls interrupted by sleep are retried."""

    async def test_retries_llm_call_after_connection_error(self) -> None:
        """Detector retries a failed LLM call after validating provider."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(
                health_check_retries=3,
                health_check_retry_delay=0.01,
            )
        )
        provider = AsyncMock()
        provider.health_check.return_value = True

        # The callable simulates an LLM generate: fails once, then succeeds
        call_count = 0

        async def flaky_generate() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection reset by sleep")
            return "response after retry"

        result = await detector.retry_after_sleep(
            provider=provider,
            operation=flaky_generate,
        )

        assert result == "response after retry"
        assert call_count == 2
        provider.health_check.assert_called()


@pytest.mark.unit
@pytest.mark.req("REQ-26.5")
class TestAuditLogging:
    """Sleep/wake events logged in audit trail."""

    async def test_logs_sleep_event_to_audit(self) -> None:
        """Sleep detection event is written to audit storage."""
        detector = SleepWakeDetector()
        storage = AsyncMock()

        await detector.log_sleep_event(storage, agent_id="agent-001")

        storage.log_audit.assert_called_once_with(
            action="sleep_detected",
            agent_id="agent-001",
            details="System sleep detected via time-drift",
        )

    async def test_logs_wake_event_to_audit(self) -> None:
        """Wake recovery event is written to audit storage."""
        detector = SleepWakeDetector()
        storage = AsyncMock()

        await detector.log_wake_event(storage, agent_id="agent-001")

        storage.log_audit.assert_called_once_with(
            action="wake_recovered",
            agent_id="agent-001",
            details="System wake — provider reconnected",
        )


@pytest.mark.unit
@pytest.mark.req("REQ-26.6")
class TestWakeBehaviorConfigurable:
    """Wake behavior is configurable via SleepWakeConfig."""

    async def test_wake_behavior_configurable(self) -> None:
        """WakeBehavior can be set to RESUME or STAY_PAUSED."""
        config_resume = SleepWakeConfig(wake_behavior=WakeBehavior.RESUME)
        config_pause = SleepWakeConfig(wake_behavior=WakeBehavior.STAY_PAUSED)

        detector_resume = SleepWakeDetector(config=config_resume)
        detector_pause = SleepWakeDetector(config=config_pause)

        assert detector_resume.should_resume() is True
        assert detector_pause.should_resume() is False


# ======================================================================
# Sleep/wake edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-24.2")
class TestSleepWakeEdgeCases:
    """Cover sleep/wake detector edge cases."""

    def test_detect_sleep_no_drift(self) -> None:
        """No time drift means no sleep detected."""
        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=5.0),
        )
        # Record current time, then check immediately -- no drift
        detector.mark_turn_start()
        slept = detector.check_for_sleep()
        assert slept is False

    def test_detect_sleep_with_drift(self) -> None:
        """Time drift above threshold triggers sleep detection."""
        import time

        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=0.01),
        )
        # Simulate time drift by manually setting last turn time in the past
        detector._last_turn_time = time.monotonic() - 10.0
        slept = detector.check_for_sleep()
        assert slept is True
        assert detector.sleep_detected is True

    def test_clear_sleep_flag(self) -> None:
        """clear_sleep_flag resets the detected state."""
        import time

        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=0.01),
        )
        detector._last_turn_time = time.monotonic() - 10.0
        detector.check_for_sleep()
        assert detector.sleep_detected is True
        detector.clear_sleep_flag()
        assert detector.sleep_detected is False

    async def test_wait_for_provider_recovery_fails(self) -> None:
        """wait_for_provider_recovery returns False after max retries."""
        from unittest.mock import AsyncMock

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False
        result = await detector.wait_for_provider_recovery(provider, max_retries=2)
        assert result is False

    async def test_retry_after_sleep_connection_error(self) -> None:
        """retry_after_sleep catches ConnectionError and retries after recovery."""
        from unittest.mock import AsyncMock

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01),
        )
        provider = AsyncMock()
        provider.health_check.return_value = True

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("lost connection")
            return "success"

        result = await detector.retry_after_sleep(provider, operation)
        assert result == "success"
        assert call_count == 2

    async def test_retry_after_sleep_recovery_fails_reraises(self) -> None:
        """retry_after_sleep re-raises if recovery fails."""
        from unittest.mock import AsyncMock

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01, health_check_retries=1),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False

        async def failing_op():
            raise ConnectionError("permanent failure")

        with pytest.raises(ConnectionError, match="permanent failure"):
            await detector.retry_after_sleep(provider, failing_op)
