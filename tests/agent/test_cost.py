"""Tests for agent/cost.py — cost estimation (REQ-10.5)."""

from __future__ import annotations

import pytest

from guild.agent.cost import COST_TABLE, estimate_cost, format_cost_summary


@pytest.mark.unit
@pytest.mark.req("REQ-10.5")
class TestCostEstimation:
    """Tests for cost estimation logic."""

    def test_ollama_is_free(self) -> None:
        """Local ollama provider should always estimate $0.00."""
        cost = estimate_cost(
            input_tokens=100_000,
            output_tokens=50_000,
            provider="ollama",
        )
        assert cost == 0.0

    def test_gemini_cli_is_free(self) -> None:
        """gemini-cli (subscription-based) should estimate $0.00."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=500_000,
            provider="gemini-cli",
        )
        assert cost == 0.0

    def test_cloud_provider_has_cost(self) -> None:
        """Cloud providers (claude-sonnet, openai-gpt4) have non-zero cost."""
        cost_sonnet = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            provider="claude-sonnet",
        )
        assert cost_sonnet > 0.0
        # claude-sonnet: $3/M input + $15/M output = $18
        assert abs(cost_sonnet - 18.0) < 0.01

        cost_gpt4 = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            provider="openai-gpt4",
        )
        assert cost_gpt4 > 0.0
        # openai-gpt4: $5/M input + $15/M output = $20
        assert abs(cost_gpt4 - 20.0) < 0.01

    def test_unknown_provider_is_free(self) -> None:
        """Unknown providers default to $0.00 (assumed local)."""
        cost = estimate_cost(
            input_tokens=500_000,
            output_tokens=250_000,
            provider="my-local-model",
        )
        assert cost == 0.0

    def test_format_cost_summary_readable(self) -> None:
        """format_cost_summary returns a human-readable string with key info."""
        summary = format_cost_summary(
            input_tokens=10_000,
            output_tokens=5_000,
            provider="claude-sonnet",
        )
        # Should contain token counts
        assert "10,000" in summary
        assert "5,000" in summary
        # Should contain dollar sign and provider
        assert "$" in summary
        assert "claude-sonnet" in summary

    def test_format_cost_summary_free_provider(self) -> None:
        """Free providers show 'free' in the summary."""
        summary = format_cost_summary(
            input_tokens=50_000,
            output_tokens=25_000,
            provider="ollama",
        )
        assert "free" in summary
        assert "ollama" in summary

    def test_cost_table_has_expected_providers(self) -> None:
        """COST_TABLE includes all documented providers."""
        expected = {"ollama", "gemini-cli", "openai-gpt4", "claude-sonnet"}
        assert expected.issubset(set(COST_TABLE.keys()))
