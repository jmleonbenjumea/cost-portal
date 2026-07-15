"""Pure cost calculation logic — no DB access, no side effects."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    price_input_mtok: float = 0.0
    price_output_mtok: float = 0.0
    price_cache_read_mtok: float = 0.0
    price_cache_creation_mtok: float = 0.0
    price_per_1k_pages: float = 0.0


# Default prices seeded at startup — kept in sync with portal_cost_config table.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "claude-haiku-4-5": ModelPrice(1.00, 5.00, 0.10, 1.25),
    "claude-haiku-4-5-20251001": ModelPrice(1.00, 5.00, 0.10, 1.25),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00, 0.30, 3.75),
    "claude-opus-4-6": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-7": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "gpt-4o": ModelPrice(2.50, 10.00, 0.125, 0.0),
    "gpt-4o-mini": ModelPrice(0.15, 0.60, 0.075, 0.0),
    "prebuilt-read": ModelPrice(price_per_1k_pages=1.50),
}


def _tok(tokens: int | None) -> int:
    return tokens or 0


def calculate_row_cost(
    *,
    model_name: str | None,
    tokens_input: int | None,
    tokens_output: int | None,
    tokens_cache_read: int | None,
    tokens_cache_creation: int | None,
    pages_processed: int | None,
    prices: dict[str, ModelPrice] | None = None,
) -> float:
    """Return the USD cost for a single api_audit_logs row."""
    if not model_name:
        return 0.0

    price_map = prices if prices is not None else DEFAULT_PRICES
    p = price_map.get(model_name)
    if p is None:
        return 0.0

    if pages_processed:
        return pages_processed * p.price_per_1k_pages / 1000

    cost = (
        _tok(tokens_input) * p.price_input_mtok / 1_000_000
        + _tok(tokens_output) * p.price_output_mtok / 1_000_000
        + _tok(tokens_cache_read) * p.price_cache_read_mtok / 1_000_000
        + _tok(tokens_cache_creation) * p.price_cache_creation_mtok / 1_000_000
    )
    return cost


def cache_savings(
    *,
    model_name: str | None,
    tokens_cache_read: int | None,
    prices: dict[str, ModelPrice] | None = None,
) -> float:
    """USD saved by cache hits vs paying full input price."""
    if not model_name or not tokens_cache_read:
        return 0.0
    price_map = prices if prices is not None else DEFAULT_PRICES
    p = price_map.get(model_name)
    if p is None:
        return 0.0
    full_price = _tok(tokens_cache_read) * p.price_input_mtok / 1_000_000
    cache_price = _tok(tokens_cache_read) * p.price_cache_read_mtok / 1_000_000
    return max(0.0, full_price - cache_price)
