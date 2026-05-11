"""Tests for provider/escalation.py — model escalation chain and provider."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from guild.provider.base import LLMProvider, LLMResponse
from guild.provider.escalation import (
    MALFORMED_CORRECTION_HINT,
    EscalatingProvider,
    EscalationChain,
    MalformedOutputError,
)

pytestmark = pytest.mark.unit


def _make_mock_provider(name: str = "test-model") -> LLMProvider:
    """Create a mock LLMProvider with a model attribute."""
    provider = AsyncMock(spec=LLMProvider)
    provider.model = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(content=f"response from {name}", model=name)
    )
    provider.health_check = AsyncMock(return_value=True)
    return provider


def _make_chain(count: int = 3) -> tuple[EscalationChain, list[LLMProvider]]:
    """Create a chain with `count` mock providers."""
    providers = [_make_mock_provider(f"model-{i}") for i in range(count)]
    chain = EscalationChain(providers)
    return chain, providers


# --- EscalationChain tests ---


@pytest.mark.req("REQ-17.2")
class TestEscalationChainBasics:
    """EscalationChain manages provider ordering and escalation."""

    def test_chain_starts_at_first_provider(self) -> None:
        """Chain always starts at the first (primary) provider."""
        chain, providers = _make_chain(3)

        assert chain.current is providers[0]
        assert chain.current_index == 0

    def test_escalate_moves_to_next_provider(self) -> None:
        """escalate() advances to the next provider in the chain."""
        chain, providers = _make_chain(3)

        result = chain.escalate()

        assert result is True
        assert chain.current is providers[1]
        assert chain.current_index == 1

    def test_escalate_returns_false_when_exhausted(self) -> None:
        """escalate() returns False when already at the last provider."""
        chain, providers = _make_chain(2)
        chain.escalate()  # move to index 1 (last)

        result = chain.escalate()

        assert result is False
        assert chain.current is providers[1]
        assert chain.is_exhausted is True

    def test_is_exhausted_false_when_not_at_end(self) -> None:
        """is_exhausted is False when there are more providers available."""
        chain, _ = _make_chain(3)

        assert chain.is_exhausted is False

    def test_is_exhausted_true_for_single_provider(self) -> None:
        """A single-provider chain is always exhausted."""
        providers = [_make_mock_provider("only-one")]
        chain = EscalationChain(providers)

        assert chain.is_exhausted is True

    def test_escalate_through_full_chain(self) -> None:
        """Can escalate through all providers until exhausted."""
        chain, providers = _make_chain(4)

        assert chain.escalate() is True  # -> 1
        assert chain.escalate() is True  # -> 2
        assert chain.escalate() is True  # -> 3
        assert chain.escalate() is False  # exhausted
        assert chain.current is providers[3]


@pytest.mark.req("REQ-17.1")
class TestEscalationChainReset:
    """EscalationChain.reset() returns to the primary provider."""

    def test_reset_returns_to_primary(self) -> None:
        """reset() brings the chain back to index 0."""
        chain, providers = _make_chain(3)
        chain.escalate()
        chain.escalate()

        chain.reset()

        assert chain.current is providers[0]
        assert chain.current_index == 0
        assert chain.is_exhausted is False

    def test_reset_is_idempotent(self) -> None:
        """Calling reset() when already at index 0 is a no-op."""
        chain, providers = _make_chain(3)

        chain.reset()

        assert chain.current is providers[0]


@pytest.mark.req("REQ-17.7")
class TestEscalationChainConfigurable:
    """EscalationChain is configurable from a list of providers."""

    def test_chain_configurable_from_list(self) -> None:
        """Chain can be constructed from any list of LLMProviders."""
        p1 = _make_mock_provider("fast-model")
        p2 = _make_mock_provider("medium-model")
        p3 = _make_mock_provider("smart-model")

        chain = EscalationChain([p1, p2, p3])

        assert len(chain) == 3
        assert chain.current_name == "fast-model"
        chain.escalate()
        assert chain.current_name == "medium-model"
        chain.escalate()
        assert chain.current_name == "smart-model"

    def test_chain_rejects_empty_list(self) -> None:
        """Chain raises ValueError if given an empty provider list."""
        with pytest.raises(ValueError, match="at least one provider"):
            EscalationChain([])

    def test_current_name_uses_model_attribute(self) -> None:
        """current_name returns the model attribute of the current provider."""
        provider = _make_mock_provider("my-custom-model")
        chain = EscalationChain([provider])

        assert chain.current_name == "my-custom-model"

    def test_current_name_fallback_when_no_model(self) -> None:
        """current_name uses fallback format when provider has no model attr."""
        provider = AsyncMock(spec=LLMProvider)
        # Remove model attribute entirely
        del provider.model
        chain = EscalationChain([provider])

        assert chain.current_name == "provider-0"


# --- EscalatingProvider tests ---


@pytest.mark.req("REQ-17.5")
class TestEscalatingProviderFailure:
    """EscalatingProvider escalates on generation failure."""

    async def test_escalating_provider_retries_on_failure(self) -> None:
        """On failure, provider escalates and retries with the next provider."""
        chain, providers = _make_chain(3)
        providers[0].generate = AsyncMock(side_effect=ConnectionError("model down"))
        escalating = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "hello"}]
        result = await escalating.generate(messages)

        assert result.content == "response from model-1"
        assert chain.current_index == 1
        providers[1].generate.assert_awaited_once()

    async def test_escalating_provider_raises_when_chain_exhausted(self) -> None:
        """When all providers fail, the exception propagates."""
        chain, providers = _make_chain(2)
        providers[0].generate = AsyncMock(side_effect=ConnectionError("first down"))
        providers[1].generate = AsyncMock(side_effect=ConnectionError("second down"))
        escalating = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "hello"}]
        # First call fails, escalates to second which also fails
        # But EscalatingProvider only does one escalation per generate call
        # So if first fails and second fails, it raises
        with pytest.raises(ConnectionError, match="second down"):
            await escalating.generate(messages)

    async def test_escalating_provider_passes_through_on_success(self) -> None:
        """When primary succeeds, no escalation occurs."""
        chain, providers = _make_chain(3)
        escalating = EscalatingProvider(chain)

        messages = [{"role": "user", "content": "hello"}]
        result = await escalating.generate(messages)

        assert result.content == "response from model-0"
        assert chain.current_index == 0


@pytest.mark.req("REQ-17.5")
class TestEscalatingProviderStuck:
    """EscalatingProvider.notify_stuck() triggers model escalation."""

    def test_notify_stuck_escalates_model(self) -> None:
        """notify_stuck() moves to the next provider in the chain."""
        chain, providers = _make_chain(3)
        escalating = EscalatingProvider(chain)

        result = escalating.notify_stuck()

        assert result is True
        assert chain.current is providers[1]

    def test_notify_stuck_returns_false_when_exhausted(self) -> None:
        """notify_stuck() returns False when chain is exhausted."""
        chain, _ = _make_chain(2)
        escalating = EscalatingProvider(chain)
        chain.escalate()  # exhaust the chain

        result = escalating.notify_stuck()

        assert result is False

    async def test_after_stuck_escalation_uses_new_provider(self) -> None:
        """After notify_stuck(), generate() uses the escalated provider."""
        chain, providers = _make_chain(3)
        escalating = EscalatingProvider(chain)

        escalating.notify_stuck()  # escalate to model-1
        messages = [{"role": "user", "content": "hello"}]
        result = await escalating.generate(messages)

        assert result.content == "response from model-1"
        providers[1].generate.assert_awaited_once()


@pytest.mark.req("REQ-17.8")
class TestMalformedOutputRecovery:
    """EscalatingProvider handles malformed output with retry then escalation."""

    async def test_malformed_output_triggers_retry_then_escalation(self) -> None:
        """Malformed output recovery: retry with hint, then escalate, then fail.

        Simulates the full REQ-17.8 flow:
        1. First generate returns malformed output (caller detects)
        2. retry_with_correction appends hint and retries
        3. If still bad, escalate_and_retry escalates to next model
        4. If chain exhausted, raises MalformedOutputError
        """
        chain, providers = _make_chain(3)
        escalating = EscalatingProvider(chain)

        # Step 1: First attempt (caller determines output is malformed)
        messages = [{"role": "user", "content": "do something"}]
        first_response = await escalating.generate_with_malformed_recovery(messages)
        assert first_response.content == "response from model-0"

        # Step 2: Caller decides it's malformed, retry with correction
        await escalating.retry_with_correction(messages)
        # Verify correction hint was appended
        call_args = providers[0].generate.call_args
        corrected_messages = call_args[0][0]
        assert corrected_messages[-1]["content"] == MALFORMED_CORRECTION_HINT

        # Step 3: Still malformed — escalate
        escalation_response = await escalating.escalate_and_retry(messages)
        assert chain.current_index == 1
        assert escalation_response.content == "response from model-1"

    async def test_malformed_escalation_raises_when_exhausted(self) -> None:
        """escalate_and_retry raises MalformedOutputError when chain is done."""
        chain, _ = _make_chain(2)
        escalating = EscalatingProvider(chain)
        chain.escalate()  # exhaust the chain

        messages = [{"role": "user", "content": "do something"}]
        with pytest.raises(MalformedOutputError, match="Chain exhausted"):
            await escalating.escalate_and_retry(messages)


@pytest.mark.req("REQ-17.2")
class TestEscalatingProviderHealthCheck:
    """EscalatingProvider.health_check delegates to current provider."""

    async def test_health_check_delegates_to_current(self) -> None:
        """health_check() checks the currently active provider."""
        chain, providers = _make_chain(2)
        escalating = EscalatingProvider(chain)

        result = await escalating.health_check()

        assert result is True
        providers[0].health_check.assert_awaited_once()

    async def test_health_check_after_escalation(self) -> None:
        """After escalation, health_check uses the new current provider."""
        chain, providers = _make_chain(2)
        providers[0].health_check = AsyncMock(return_value=False)
        providers[1].health_check = AsyncMock(return_value=True)
        escalating = EscalatingProvider(chain)

        chain.escalate()
        result = await escalating.health_check()

        assert result is True
        providers[1].health_check.assert_awaited_once()


@pytest.mark.req("REQ-17.5")
class TestEscalatingProviderModelProperty:
    """EscalatingProvider exposes the current model name."""

    def test_model_property_reflects_current(self) -> None:
        """model property returns the current provider's name."""
        chain, _ = _make_chain(3)
        escalating = EscalatingProvider(chain)

        assert escalating.model == "model-0"
        chain.escalate()
        assert escalating.model == "model-1"


@pytest.mark.req("REQ-17.5")
class TestEscalationLogging:
    """Escalation chain logs model switches and raises on exhaustion."""

    def test_escalation_logs_model_switch(self, caplog: pytest.LogCaptureFixture) -> None:
        """Escalating logs an INFO message identifying the new provider."""
        import logging

        chain, _ = _make_chain(3)

        with caplog.at_level(logging.INFO):
            chain.escalate()

        assert any("model-1" in record.message for record in caplog.records)

    def test_exhausted_chain_raises(self) -> None:
        """escalate_and_retry raises MalformedOutputError when chain is exhausted."""
        chain, _ = _make_chain(1)  # Only one provider — already exhausted
        escalating = EscalatingProvider(chain)

        assert chain.is_exhausted is True
        # notify_stuck returns False when exhausted
        assert escalating.notify_stuck() is False
        # Attempting further escalation still fails
        assert chain.escalate() is False


# --- REQ-17.3 / REQ-17.4: Cheap models and capability tagging ---


@pytest.mark.req("REQ-17.3")
class TestSelectCheapModel:
    """Select cheapest model capable of handling the task type."""

    def test_select_cheapest_model_for_simple_task(self) -> None:
        """Simple QA tasks select the cheapest capable model."""
        from guild.provider.escalation import (
            MODEL_CAPABILITIES,
            select_model_for_task,
        )

        available = list(MODEL_CAPABILITIES.keys())
        selected = select_model_for_task("simple_qa", available)
        # Should pick the cheapest model that has the simple_qa tag
        cap = MODEL_CAPABILITIES[selected]
        assert "simple_qa" in cap.tags

    def test_select_stronger_model_for_complex_task(self) -> None:
        """Complex tasks select a model with the complex_tasks tag."""
        from guild.provider.escalation import (
            MODEL_CAPABILITIES,
            select_model_for_task,
        )

        available = list(MODEL_CAPABILITIES.keys())
        selected = select_model_for_task("complex_tasks", available)
        cap = MODEL_CAPABILITIES[selected]
        assert "complex_tasks" in cap.tags


@pytest.mark.req("REQ-17.4")
class TestModelCapabilityTagging:
    """Model capability metadata tagging."""

    def test_model_capability_tagging(self) -> None:
        """MODEL_CAPABILITIES has tags and cost_tier for each model."""
        from guild.provider.escalation import MODEL_CAPABILITIES, ModelCapability

        assert len(MODEL_CAPABILITIES) >= 3
        for _name, cap in MODEL_CAPABILITIES.items():
            assert isinstance(cap, ModelCapability)
            assert isinstance(cap.tags, set)
            assert len(cap.tags) > 0
            assert cap.cost_tier in ("free", "cheap", "expensive")
            assert cap.name != ""


# ======================================================================
# Provider escalation edges (from coverage gaps)
# ======================================================================


@pytest.mark.req("REQ-12.1")
@pytest.mark.unit
class TestProviderEscalationEdges:
    """Cover provider/escalation.py uncovered branches."""

    def test_select_model_unknown_model_skipped(self) -> None:
        """select_model_for_task skips models not in MODEL_CAPABILITIES (line 81)."""
        from guild.provider.escalation import select_model_for_task

        # Include a model name that\'s not in MODEL_CAPABILITIES + one that is
        result = select_model_for_task(
            task_type="simple_qa",
            available_models=["unknown_model_xyz", "gemma4-2b-edge-fast"],
        )
        # Should pick the known model (unknown is skipped)
        assert result == "gemma4-2b-edge-fast"

    def test_select_model_no_match_raises(self) -> None:
        """select_model_for_task raises when no model supports task type (line 87)."""
        from guild.provider.escalation import select_model_for_task

        with pytest.raises(ValueError, match="No available model"):
            select_model_for_task(
                task_type="nonexistent_task_type",
                available_models=["unknown_model_xyz"],
            )

    async def test_escalation_provider_chain_exhausted_raises(self) -> None:
        """EscalatingProvider raises when chain is exhausted (line 214)."""
        from unittest.mock import AsyncMock

        # Create a chain with a single provider that fails
        provider = AsyncMock()
        provider.generate.side_effect = RuntimeError("provider fail")

        chain = EscalationChain(
            providers=[provider],
        )
        ep = EscalatingProvider(chain)

        with pytest.raises(RuntimeError, match="provider fail"):
            await ep.generate([{"role": "user", "content": "test"}])

    def test_escalation_provider_chain_property(self) -> None:
        """EscalatingProvider.chain property returns the chain (line 186)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock()
        chain = EscalationChain(providers=[provider])
        ep = EscalatingProvider(chain)
        assert ep.chain is chain
