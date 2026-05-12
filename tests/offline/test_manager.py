"""Tests for offline-first management."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.offline.manager import OfflineManager


class FakeProvider:
    """Fake LLM provider for testing."""

    def __init__(self, healthy: bool = True) -> None:
        self._healthy = healthy
        self.health_check = AsyncMock(return_value=healthy)


@pytest.mark.unit
async def test_works_without_internet() -> None:
    """Core OfflineManager functions work even when provider is offline."""
    provider = FakeProvider(healthy=False)
    mgr = OfflineManager(provider)

    # check_connectivity should return False but not crash
    result = await mgr.check_connectivity()
    assert result is False
    assert mgr.is_online is False

    # Offline docs still work without connectivity
    help_text = mgr.get_help("getting-started")
    assert help_text is not None
    assert "guild init" in help_text.lower()


@pytest.mark.unit
async def test_graceful_degradation_no_crash() -> None:
    """When health_check raises, manager degrades gracefully."""
    provider = FakeProvider(healthy=True)
    provider.health_check = AsyncMock(side_effect=ConnectionError("no conn"))
    mgr = OfflineManager(provider)

    # Should not raise
    result = await mgr.check_connectivity()
    assert result is False
    assert mgr.is_online is False

    # Help still accessible
    assert mgr.get_help("commands") is not None


@pytest.mark.unit
async def test_list_local_models() -> None:
    """list_local_models parses ollama list output."""
    fake_output = (
        "NAME              ID          SIZE    MODIFIED\n"
        "qwen2.5:latest    abc123      4.7 GB  2 days ago\n"
        "codellama:7b      def456      3.8 GB  1 week ago\n"
    )
    mgr = OfflineManager(FakeProvider())

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc_mock = AsyncMock()
        proc_mock.communicate.return_value = (
            fake_output.encode(),
            b"",
        )
        proc_mock.returncode = 0
        mock_exec.return_value = proc_mock

        models = await mgr.list_local_models()

    assert "qwen2.5:latest" in models
    assert "codellama:7b" in models
    assert len(models) == 2


@pytest.mark.unit
async def test_offline_help_returns_content() -> None:
    """get_help returns content for known topics, None for unknown."""
    mgr = OfflineManager(FakeProvider())

    assert mgr.get_help("models") is not None
    assert "ollama" in mgr.get_help("models").lower()
    assert mgr.get_help("commands") is not None
    assert mgr.get_help("troubleshooting") is not None
    assert mgr.get_help("nonexistent-topic") is None


# ======================================================================
# Offline manager edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestOfflineManagerEdgeCases:
    """Offline manager check_connectivity exception path."""

    async def test_connectivity_exception_sets_offline(self) -> None:
        """If health_check raises, is_online is set to False."""
        provider = AsyncMock()
        provider.health_check.side_effect = ConnectionError("connection refused")
        mgr = OfflineManager(provider=provider)
        result = await mgr.check_connectivity()
        assert result is False
        assert mgr.is_online is False


# ======================================================================
# Offline manager health check success (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestOfflineManagerHealthCheckSuccess:
    """Cover the branch where health check succeeds (line 45->exit)."""

    async def test_check_connectivity_success(self) -> None:
        """When health_check returns True, connectivity is True."""
        from unittest.mock import AsyncMock, MagicMock

        provider = MagicMock()
        provider.health_check = AsyncMock(return_value=True)

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()

        assert result is True
        assert mgr.is_online is True

    async def test_check_connectivity_false(self) -> None:
        """When health_check returns False, connectivity is False (exit branch)."""
        from unittest.mock import AsyncMock, MagicMock

        provider = MagicMock()
        provider.health_check = AsyncMock(return_value=False)

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()

        # This exercises the path where result = False (line 45 -> exit)
        assert result is False
        assert mgr.is_online is False
