from dataclasses import dataclass
from typing import FrozenSet

from trading.models import RiskDecision, TradeProposal


@dataclass(frozen=True)
class RiskLimits:
    trading_enabled: bool
    allowed_symbols: FrozenSet[str]
    max_quantity: int
    max_order_value: float
    max_risk_per_order: float


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def validate(self, proposal: TradeProposal) -> RiskDecision:
        if not self._limits.trading_enabled:
            return self._reject("Trading is DISARMED")

        if proposal.symbol not in self._limits.allowed_symbols:
            return self._reject("Symbol is not on the allowlist")

        if proposal.quantity <= 0:
            return self._reject("Quantity must be positive")

        if proposal.quantity > self._limits.max_quantity:
            return self._reject("Quantity exceeds the configured maximum")

        if proposal.limit_price <= 0:
            return self._reject("Limit price must be positive")

        order_value = proposal.quantity * proposal.limit_price
        if order_value > self._limits.max_order_value:
            return self._reject("Order value exceeds the configured maximum")

        if proposal.stop_price is None:
            return RiskDecision(True, "APPROVED", "All configured checks passed")

        if proposal.stop_price <= 0:
            return self._reject("Stop price must be positive")

        if proposal.side == "BUY" and proposal.stop_price >= proposal.limit_price:
            return self._reject("A long position stop must be below its entry")

        if proposal.side == "SELL" and proposal.stop_price <= proposal.limit_price:
            return self._reject("A short position stop must be above its entry")

        order_risk = proposal.quantity * abs(
            proposal.limit_price - proposal.stop_price
        )
        if order_risk > self._limits.max_risk_per_order:
            return self._reject("Order risk exceeds the configured maximum")

        return RiskDecision(True, "APPROVED", "All configured checks passed")

    @staticmethod
    def _reject(reason: str) -> RiskDecision:
        return RiskDecision(False, "REJECTED", reason)
