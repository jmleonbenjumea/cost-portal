"""Tests for the pure cost calculation logic."""
import pytest

from app.cost_engine import ModelPrice, cache_savings, calculate_row_cost

_PRICES = {
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00, 0.30, 3.75),
    "prebuilt-read": ModelPrice(price_per_1k_pages=1.50),
}


class TestCalculateRowCost:
    def test_returns_zero_for_unknown_model(self):
        assert calculate_row_cost(
            model_name="unknown-model",
            tokens_input=1000, tokens_output=500,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=None, prices=_PRICES,
        ) == 0.0

    def test_returns_zero_when_model_is_none(self):
        assert calculate_row_cost(
            model_name=None,
            tokens_input=1000, tokens_output=500,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=None,
        ) == 0.0

    def test_token_cost_calculation(self):
        # 1M input tokens at $3/MTok = $3, 1M output at $15/MTok = $15 → $18
        cost = calculate_row_cost(
            model_name="claude-sonnet-4-6",
            tokens_input=1_000_000, tokens_output=1_000_000,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=None, prices=_PRICES,
        )
        assert cost == pytest.approx(18.0)

    def test_cache_read_tokens_use_cache_price(self):
        # 1M cache-read tokens at $0.30/MTok = $0.30
        cost = calculate_row_cost(
            model_name="claude-sonnet-4-6",
            tokens_input=0, tokens_output=0,
            tokens_cache_read=1_000_000, tokens_cache_creation=None,
            pages_processed=None, prices=_PRICES,
        )
        assert cost == pytest.approx(0.30)

    def test_cache_creation_tokens(self):
        # 1M cache-creation tokens at $3.75/MTok = $3.75
        cost = calculate_row_cost(
            model_name="claude-sonnet-4-6",
            tokens_input=0, tokens_output=0,
            tokens_cache_read=None, tokens_cache_creation=1_000_000,
            pages_processed=None, prices=_PRICES,
        )
        assert cost == pytest.approx(3.75)

    def test_pages_processed_uses_per_page_price(self):
        # 1000 pages at $1.50/1k = $1.50
        cost = calculate_row_cost(
            model_name="prebuilt-read",
            tokens_input=None, tokens_output=None,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=1000, prices=_PRICES,
        )
        assert cost == pytest.approx(1.50)

    def test_pages_takes_precedence_over_tokens(self):
        # When pages_processed is set, token fields are ignored
        cost_with_tokens = calculate_row_cost(
            model_name="prebuilt-read",
            tokens_input=1_000_000, tokens_output=1_000_000,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=1000, prices=_PRICES,
        )
        cost_without_tokens = calculate_row_cost(
            model_name="prebuilt-read",
            tokens_input=None, tokens_output=None,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=1000, prices=_PRICES,
        )
        assert cost_with_tokens == cost_without_tokens

    def test_none_token_fields_treated_as_zero(self):
        cost = calculate_row_cost(
            model_name="claude-sonnet-4-6",
            tokens_input=None, tokens_output=None,
            tokens_cache_read=None, tokens_cache_creation=None,
            pages_processed=None, prices=_PRICES,
        )
        assert cost == 0.0


class TestCacheSavings:
    def test_savings_equals_full_minus_cache_price(self):
        # Full price: 1M tokens × $3/MTok = $3. Cache price: 1M × $0.30 = $0.30. Savings = $2.70
        savings = cache_savings(
            model_name="claude-sonnet-4-6",
            tokens_cache_read=1_000_000,
            prices=_PRICES,
        )
        assert savings == pytest.approx(2.70)

    def test_no_savings_when_no_cache_tokens(self):
        assert cache_savings(
            model_name="claude-sonnet-4-6",
            tokens_cache_read=None,
            prices=_PRICES,
        ) == 0.0

    def test_no_savings_when_model_is_none(self):
        assert cache_savings(model_name=None, tokens_cache_read=1000) == 0.0

    def test_no_savings_for_unknown_model(self):
        assert cache_savings(
            model_name="unknown", tokens_cache_read=1000, prices=_PRICES
        ) == 0.0
