"""Tests for the Billing Hard-Fuse (WO-A2.3).

Verifies:
- Initial spend is zero, fuse is untripped
- Recording usage updates cumulative spend correctly
- Budget cap trips the fuse at the right threshold
- Multiple small charges accumulate to trip
- Different model pricing is respected
- Revoke callback is invoked on trip
- Reset clears all state
- Post-trip calls are always rejected
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from security.billing_fuse import (
    BillingFuse,
    BillingFuseConfig,
    TokenUsage,
    DEFAULT_PRICING,
)
from agentos_kernel.exceptions import BillingFuseTrippedError


@pytest.fixture
def fuse() -> BillingFuse:
    """Billing fuse with default $0.50 budget."""
    return BillingFuse(BillingFuseConfig(budget_cap_usd=0.50))


@pytest.fixture
def tiny_fuse() -> BillingFuse:
    """Billing fuse with very small budget for quick trip tests."""
    return BillingFuse(BillingFuseConfig(budget_cap_usd=0.0001))


class TestInitialState:
    """Verify fuse initial state."""

    def test_initial_spend_zero(self, fuse):
        assert fuse.cumulative_spend == 0.0

    def test_initial_budget_remaining(self, fuse):
        assert fuse.budget_remaining == 0.50

    def test_initial_not_tripped(self, fuse):
        assert fuse.is_tripped is False

    def test_initial_usage_count_zero(self, fuse):
        assert fuse.usage_count == 0


class TestTokenUsage:
    """TokenUsage data class."""

    def test_token_usage_repr(self):
        """TokenUsage can be created and inspected."""
        usage = TokenUsage(
            prompt_tokens=500,
            completion_tokens=200,
            model="claude-sonnet-4",
        )
        assert usage.prompt_tokens == 500
        assert usage.completion_tokens == 200
        assert usage.model == "claude-sonnet-4"

    def test_token_usage_frozen(self):
        """TokenUsage is immutable."""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, model="gpt-4o")
        with pytest.raises(Exception):
            usage.prompt_tokens = 200  # type: ignore


class TestBillingAccumulation:
    """Token spend accumulation."""

    def test_single_usage_updates_spend(self, fuse):
        """Recording usage should increase cumulative spend."""
        spend = fuse.record_usage(
            TokenUsage(prompt_tokens=50, completion_tokens=10, model="claude-sonnet-4")
        )
        assert spend > 0.0
        assert fuse.cumulative_spend == spend
        assert fuse.usage_count == 1

    def test_multiple_charges_accumulate(self, fuse):
        """Several small charges sum correctly."""
        s1 = fuse.record_usage(
            TokenUsage(prompt_tokens=50, completion_tokens=10, model="claude-sonnet-4")
        )
        s2 = fuse.record_usage(
            TokenUsage(prompt_tokens=30, completion_tokens=5, model="claude-sonnet-4")
        )
        assert s2 > s1
        assert fuse.cumulative_spend == s2

    def test_budget_remaining_decreases(self, fuse):
        """budget_remaining should decrease with usage."""
        initial = fuse.budget_remaining
        fuse.record_usage(
            TokenUsage(prompt_tokens=50, completion_tokens=10, model="claude-sonnet-4")
        )
        assert fuse.budget_remaining < initial


class TestBudgetTrip:
    """Budget cap enforcement."""

    def test_budget_not_exceeded_no_trip(self, fuse):
        """Under-budget usage does not trip."""
        fuse.record_usage(
            TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
        )
        assert fuse.is_tripped is False

    def test_budget_exceeded_trips_fuse(self, tiny_fuse):
        """Over-budget usage raises BillingFuseTrippedError."""
        with pytest.raises(BillingFuseTrippedError) as exc:
            tiny_fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        assert exc.value.budget_usd == 0.0001
        assert exc.value.spent_usd > 0.0001
        assert tiny_fuse.is_tripped is True

    def test_post_trip_calls_rejected(self, tiny_fuse):
        """After tripping, all subsequent calls raise error."""
        try:
            tiny_fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        except BillingFuseTrippedError:
            pass

        with pytest.raises(BillingFuseTrippedError):
            tiny_fuse.record_usage(
                TokenUsage(prompt_tokens=1, completion_tokens=1, model="claude-sonnet-4")
            )

    def test_multiple_small_charges_accumulate_to_trip(self):
        """Many small charges should eventually trip when cumulative > budget."""
        fuse = BillingFuse(BillingFuseConfig(budget_cap_usd=0.0005))
        tripped = False
        for i in range(20):
            try:
                fuse.record_usage(
                    TokenUsage(prompt_tokens=5, completion_tokens=2, model="claude-sonnet-4")
                )
            except BillingFuseTrippedError:
                tripped = True
                break
        assert tripped, f"Should have tripped after {i+1} charges (spent=${fuse.cumulative_spend:.4f})"


class TestPricingTable:
    """Model pricing lookup."""

    def test_default_pricing_table_has_models(self):
        """Default pricing table includes common models."""
        assert "claude-sonnet-4" in DEFAULT_PRICING
        assert "gpt-4o" in DEFAULT_PRICING

    def test_different_model_different_cost(self):
        """GPT-4 costs more per token than GPT-3.5."""
        # Use separate fuses to compare
        fuse_expensive = BillingFuse(BillingFuseConfig(budget_cap_usd=100.0))
        fuse_cheap = BillingFuse(BillingFuseConfig(budget_cap_usd=100.0))

        fuse_expensive.record_usage(
            TokenUsage(prompt_tokens=1000, completion_tokens=0, model="gpt-4")
        )
        fuse_cheap.record_usage(
            TokenUsage(prompt_tokens=1000, completion_tokens=0, model="gpt-3.5-turbo")
        )
        # gpt-4: $30.00/1K vs gpt-3.5-turbo: $0.50/1K
        assert fuse_expensive.cumulative_spend > fuse_cheap.cumulative_spend

    def test_unknown_model_uses_default_rates(self):
        """Unknown model uses fallback rates."""
        fuse = BillingFuse(BillingFuseConfig(budget_cap_usd=100.0))
        cost = fuse.record_usage(
            TokenUsage(prompt_tokens=1000, completion_tokens=0, model="unknown-model")
        )
        # Default: $3.00/1M prompt
        assert cost == pytest.approx(0.003)


class TestRevokeCallback:
    """Credential revocation on trip."""

    def test_revoke_callback_invoked(self):
        """When revoke_on_trip=True, callback is called."""
        was_called = []

        def on_revoke():
            was_called.append(True)

        fuse = BillingFuse(
            BillingFuseConfig(budget_cap_usd=0.0001, revoke_on_trip=True),
            revoke_callback=on_revoke,
        )
        try:
            fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        except BillingFuseTrippedError:
            pass
        assert len(was_called) == 1

    def test_revoke_disabled_does_not_call(self):
        """When revoke_on_trip=False, callback is not called."""
        was_called = []

        def on_revoke():
            was_called.append(True)

        fuse = BillingFuse(
            BillingFuseConfig(budget_cap_usd=0.0001, revoke_on_trip=False),
            revoke_callback=on_revoke,
        )
        try:
            fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        except BillingFuseTrippedError:
            pass
        assert len(was_called) == 0


class TestReset:
    """Reset functionality."""

    def test_reset_clears_spend(self, fuse):
        """Reset should return cumulative spend to zero."""
        fuse.record_usage(
            TokenUsage(prompt_tokens=50, completion_tokens=10, model="claude-sonnet-4")
        )
        assert fuse.cumulative_spend > 0.0
        fuse.reset()
        assert fuse.cumulative_spend == 0.0

    def test_reset_untrips_fuse(self, tiny_fuse):
        """Reset should clear the tripped state."""
        try:
            tiny_fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        except BillingFuseTrippedError:
            pass
        assert tiny_fuse.is_tripped is True
        tiny_fuse.reset()
        assert tiny_fuse.is_tripped is False

    def test_reset_allows_new_calls(self):
        """After reset, new calls should work again (until trip again)."""
        fuse = BillingFuse(BillingFuseConfig(budget_cap_usd=0.05))
        try:
            fuse.record_usage(
                TokenUsage(prompt_tokens=100, completion_tokens=10, model="claude-sonnet-4")
            )
        except BillingFuseTrippedError:
            pass
        fuse.reset()
        # Small call should work with fresh budget
        cost = fuse.record_usage(
            TokenUsage(prompt_tokens=1, completion_tokens=1, model="claude-sonnet-4")
        )
        assert cost > 0.0
        assert fuse.usage_count == 1
