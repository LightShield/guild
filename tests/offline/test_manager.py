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
@pytest.mark.req("REQ-21.1")
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
@pytest.mark.req("REQ-21.2")
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
@pytest.mark.req("REQ-21.3")
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
@pytest.mark.req("REQ-21.4")
async def test_offline_help_returns_content() -> None:
    """get_help returns content for known topics, None for unknown."""
    mgr = OfflineManager(FakeProvider())

    assert mgr.get_help("models") is not None
    assert "ollama" in mgr.get_help("models").lower()
    assert mgr.get_help("commands") is not None
    assert mgr.get_help("troubleshooting") is not None
    assert mgr.get_help("nonexistent-topic") is None
