"""Basic token cost estimates, without cache discounts or currency conversion."""

from decimal import Decimal

from .schemas import Price

_TOKENS_PER_MILLION = Decimal("1000000")


def estimate_basic(price: Price, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Return unknown unless both rates exist; zero is a known free rate."""
    for tokens in (input_tokens, output_tokens):
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise ValueError("token counts must be nonnegative integers")
    if price.input_per_million is None or price.output_per_million is None:
        return None
    return (
        price.input_per_million * input_tokens + price.output_per_million * output_tokens
    ) / _TOKENS_PER_MILLION
