"""Deterministic Paper-risk limit scaling from verified account equity.

The result is a configuration input, never an approval by itself.  Execution
still has to pass the non-bypassable order, session, data-quality, and account
gates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceRiskPolicy:
    max_order_pct: float = 0.02
    max_symbol_pct: float = 0.05
    max_gross_pct: float = 0.25
    max_risk_per_order_pct: float = 0.005
    max_quantity: int = 20


@dataclass(frozen=True)
class ScaledRiskLimits:
    account_equity: float
    max_order_value: float
    max_symbol_exposure: float
    max_gross_exposure: float
    max_risk_per_order: float
    max_quantity: int


def scale_risk_limits(account_equity: float, policy: BalanceRiskPolicy = BalanceRiskPolicy()) -> ScaledRiskLimits:
    """Return conservative limits proportional to a fresh, positive equity value."""
    if account_equity <= 0:
        raise ValueError("account_equity must be positive and fresh before scaling risk limits")
    for name, value in (
        ("max_order_pct", policy.max_order_pct),
        ("max_symbol_pct", policy.max_symbol_pct),
        ("max_gross_pct", policy.max_gross_pct),
        ("max_risk_per_order_pct", policy.max_risk_per_order_pct),
    ):
        if not 0 < value <= 1:
            raise ValueError(f"{name} must be in (0, 1]")
    return ScaledRiskLimits(
        account_equity=account_equity,
        max_order_value=round(account_equity * policy.max_order_pct, 2),
        max_symbol_exposure=round(account_equity * policy.max_symbol_pct, 2),
        max_gross_exposure=round(account_equity * policy.max_gross_pct, 2),
        max_risk_per_order=round(account_equity * policy.max_risk_per_order_pct, 2),
        max_quantity=policy.max_quantity,
    )
