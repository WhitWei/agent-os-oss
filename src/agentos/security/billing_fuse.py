"""Billing Hard-Fuse — post-dispatch token cost tracking with budget enforcement.

Implements WO-A2.3 billing fuse: after each LLM call, record token usage
and compute cumulative dollar cost. When spend exceeds the budget cap
(default $0.50), the fuse trips and raises BillingFuseTrippedError.

A revoke callback can be registered to deactivate API credentials on trip.

Usage::

    from agentos.security.billing_fuse import BillingFuse, BillingFuseConfig, TokenUsage

    fuse = BillingFuse(BillingFuseConfig(budget_cap_usd=0.50))
    fuse.record_usage(TokenUsage(prompt_tokens=500, completion_tokens=200, model="claude-sonnet-4"))
    # ...
    if fuse.is_tripped:
        print("Budget exhausted!")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from agentos.kernel.exceptions import BillingFuseTrippedError

logger = logging.getLogger(__name__)

# ── Default Pricing Table (USD per 1M tokens) ──

DEFAULT_PRICING = {
    # Claude models
    "claude-sonnet-4-20250514": {"prompt": 3.00, "completion": 15.00},
    "claude-sonnet-4": {"prompt": 3.00, "completion": 15.00},
    "claude-opus-4-20250514": {"prompt": 15.00, "completion": 75.00},
    "claude-opus-4": {"prompt": 15.00, "completion": 75.00},
    "claude-haiku-4-5-20251001": {"prompt": 1.00, "completion": 5.00},
    "claude-haiku-4-5": {"prompt": 1.00, "completion": 5.00},
    # GPT models
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4": {"prompt": 30.00, "completion": 60.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
}


# ── Data Structures ──


@dataclass(frozen=True)
class TokenUsage:
    """A single LLM token usage event."""

    prompt_tokens: int
    completion_tokens: int
    model: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BillingFuseConfig:
    """Configuration for the billing hard-fuse."""

    budget_cap_usd: float = 0.50
    pricing_table: dict = field(default_factory=lambda: DEFAULT_PRICING.copy())
    revoke_on_trip: bool = True
    default_prompt_rate: float = 3.00       # Fallback if model not in table
    default_completion_rate: float = 15.00


# ── Billing Fuse ──


class BillingFuse:
    """Tracks cumulative LLM token spend and enforces a hard budget cap.

    Post-dispatch hook: after each LLM call, record the token usage.
    If cumulative spend exceeds the budget, the fuse trips and:
    1. Raises BillingFuseTrippedError
    2. Calls the revoke_callback (if provided) to deactivate credentials
    """

    def __init__(
        self,
        config: Optional[BillingFuseConfig] = None,
        revoke_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config or BillingFuseConfig()
        self._revoke_callback = revoke_callback
        self._spend_usd: float = 0.0
        self._usage_history: list[TokenUsage] = []
        self._tripped: bool = False

        logger.info(
            "BillingFuse initialized: budget=$%.2f models=%d",
            self.config.budget_cap_usd,
            len(self.config.pricing_table),
        )

    # ── Public API ──

    def record_usage(self, usage: TokenUsage) -> float:
        """Record token usage from an LLM call.

        Args:
            usage: Token counts and model identifier.

        Returns:
            Cumulative spend in USD after this record.

        Raises:
            BillingFuseTrippedError: If cumulative spend exceeds the budget cap.
        """
        if self._tripped:
            raise BillingFuseTrippedError(
                f"Billing fuse already tripped. Cumulative spend: ${self._spend_usd:.4f} / "
                f"${self.config.budget_cap_usd:.2f}",
                budget_usd=self.config.budget_cap_usd,
                spent_usd=self._spend_usd,
            )

        cost = self._calculate_cost(usage)
        self._spend_usd += cost
        self._usage_history.append(usage)

        logger.debug(
            "Billing: +$%.6f (%d prompt + %d completion tokens, model=%s). "
            "Cumulative: $%.4f / $%.2f",
            cost,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.model,
            self._spend_usd,
            self.config.budget_cap_usd,
        )

        if self._spend_usd > self.config.budget_cap_usd:
            self._tripped = True
            logger.warning(
                "Billing fuse TRIPPED! Spend $%.4f exceeds budget $%.2f",
                self._spend_usd,
                self.config.budget_cap_usd,
            )

            # Revoke credentials if configured
            if self.config.revoke_on_trip and self._revoke_callback:
                try:
                    self._revoke_callback()
                    logger.info("Revoke callback executed.")
                except Exception as exc:
                    logger.error("Revoke callback failed: %s", exc)

            raise BillingFuseTrippedError(
                f"Budget exceeded: ${self._spend_usd:.4f} spent of "
                f"${self.config.budget_cap_usd:.2f} cap. "
                f"All further LLM calls are blocked.",
                budget_usd=self.config.budget_cap_usd,
                spent_usd=self._spend_usd,
            )

        return self._spend_usd

    def reset(self) -> None:
        """Reset cumulative spend and untrip the fuse."""
        self._spend_usd = 0.0
        self._usage_history.clear()
        self._tripped = False
        logger.info("BillingFuse reset — spend cleared, fuse untripped.")

    # ── Properties ──

    @property
    def cumulative_spend(self) -> float:
        """Total USD spent this session."""
        return self._spend_usd

    @property
    def budget_remaining(self) -> float:
        """Remaining budget in USD."""
        return max(0.0, self.config.budget_cap_usd - self._spend_usd)

    @property
    def is_tripped(self) -> bool:
        """Whether the billing fuse has tripped."""
        return self._tripped

    @property
    def usage_count(self) -> int:
        """Number of recorded usage events."""
        return len(self._usage_history)

    # ── Internal ──

    def _calculate_cost(self, usage: TokenUsage) -> float:
        """Calculate dollar cost for a token usage event.

        Looks up the model's pricing; falls back to defaults if unknown.
        """
        rates = self.config.pricing_table.get(
            usage.model,
            {
                "prompt": self.config.default_prompt_rate,
                "completion": self.config.default_completion_rate,
            },
        )
        prompt_cost = (usage.prompt_tokens / 1_000_000.0) * rates["prompt"]
        completion_cost = (usage.completion_tokens / 1_000_000.0) * rates["completion"]
        return prompt_cost + completion_cost
