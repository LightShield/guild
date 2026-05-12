"""Cost estimation for LLM providers (REQ-10.5).

Provides approximate cost calculations based on token usage and provider
pricing. Local providers (ollama, gemini-cli) are free.
"""

from __future__ import annotations

__all__ = ["COST_TABLE", "estimate_cost", "format_cost_summary"]

# Approximate costs per 1M tokens (USD) for known providers
COST_TABLE: dict[str, dict[str, float]] = {
    "ollama": {"input": 0.0, "output": 0.0},
    "gemini-cli": {"input": 0.0, "output": 0.0},
    "openai-gpt4": {"input": 5.0, "output": 15.0},
    "openai-gpt4o": {"input": 2.5, "output": 10.0},
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "claude-opus": {"input": 15.0, "output": 75.0},
    "claude-haiku": {"input": 0.25, "output": 1.25},
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    provider: str = "ollama",
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> float:
    """Estimate cost in USD for token usage.

    When custom per-million pricing is provided via *input_cost_per_million*
    and/or *output_cost_per_million*, those values override the built-in
    COST_TABLE lookup. Returns 0.0 for unknown providers (assumes local/free).
    """
    rates = COST_TABLE.get(provider, {"input": 0.0, "output": 0.0})
    in_rate = input_cost_per_million if input_cost_per_million is not None else rates["input"]
    out_rate = output_cost_per_million if output_cost_per_million is not None else rates["output"]
    input_cost = (input_tokens / 1_000_000) * in_rate
    output_cost = (output_tokens / 1_000_000) * out_rate
    return input_cost + output_cost


def format_cost_summary(
    input_tokens: int,
    output_tokens: int,
    provider: str,
) -> str:
    """Human-readable cost summary string.

    Example: "1,234 in / 567 out tokens (~$0.0123 USD, provider: claude-sonnet)"
    """
    cost = estimate_cost(input_tokens, output_tokens, provider)
    total_tokens = input_tokens + output_tokens

    if cost == 0.0:
        return (
            f"{input_tokens:,} in / {output_tokens:,} out tokens"
            f" ({total_tokens:,} total, free — {provider})"
        )

    return (
        f"{input_tokens:,} in / {output_tokens:,} out tokens"
        f" (~${cost:.4f} USD, provider: {provider})"
    )
