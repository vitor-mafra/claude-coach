"""Static price table per (provider, model) — USD per 1M tokens.

Update when OpenAI/Anthropic change prices. Values reflect public list pricing
known as of early 2026. Unknown models return None (cost not tracked).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    input_per_m: float  # USD per 1M input tokens
    output_per_m: float  # USD per 1M output tokens


PRICE_TABLE: dict[tuple[str, str], Pricing] = {
    # OpenAI — gpt-5 / gpt-5.5 placeholders. Refresh from
    # https://platform.openai.com/docs/pricing once we have real numbers.
    ("openai", "gpt-5"): Pricing(input_per_m=0.0, output_per_m=0.0),
    ("openai", "gpt-5.5"): Pricing(input_per_m=0.0, output_per_m=0.0),
    ("openai", "gpt-4o"): Pricing(input_per_m=2.50, output_per_m=10.00),
    ("openai", "gpt-4o-mini"): Pricing(input_per_m=0.15, output_per_m=0.60),
    # Anthropic — listed for completeness; rates are reference values, refresh
    # before relying on numbers for budgeting.
    ("anthropic", "claude-sonnet-4-6"): Pricing(input_per_m=3.00, output_per_m=15.00),
    ("anthropic", "claude-haiku-4-5-20251001"): Pricing(input_per_m=0.80, output_per_m=4.00),
}


def estimate_cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    price = PRICE_TABLE.get((provider, model))
    if price is None:
        return None
    return (
        input_tokens * price.input_per_m + output_tokens * price.output_per_m
    ) / 1_000_000
