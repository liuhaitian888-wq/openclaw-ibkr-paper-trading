from dataclasses import dataclass
import math
from typing import FrozenSet

from trading.models import RiskDecision, TradeProposal


@dataclass(frozen=True)
class RiskLimits:
    trading_enabled: bool
    allowed_symbols: FrozenSet[str]
    max_quantity: int
    max_order_value: float
    max_risk_per_order: float
    require_protective_stop: bool = True
    max_symbol_exposure: float | None = None
    max_gross_exposure: float | None = None


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def validate(
        self,
        proposal: TradeProposal,
        *,
        current_symbol_exposure: float = 0.0,
        current_gross_exposure: float = 0.0,
    ) -> RiskDecision:
        def nonnegative_number(value):
            return type(value) in (int, float) and math.isfinite(value) and value >= 0

        if (type(proposal.quantity) is not int or proposal.quantity <= 0
                or proposal.side not in ('BUY', 'SELL')):
            return self._reject('Positive integer quantity and BUY/SELL side required')
        for value in (proposal.limit_price, proposal.stop_price):
            if value is not None and not nonnegative_number(value):
                return self._reject('Finite numeric entry and stop prices required')
        if proposal.limit_price is None:
            return self._reject('Finite numeric entry price required')
        if not all(nonnegative_number(v) for v in (current_symbol_exposure, current_gross_exposure)):
            return self._reject('Finite nonnegative portfolio exposure required')
        if type(self._limits.max_quantity) is not int or self._limits.max_quantity <= 0:
            return self._reject('Invalid configured quantity maximum')
        for value in (self._limits.max_order_value, self._limits.max_risk_per_order,
                      self._limits.max_symbol_exposure, self._limits.max_gross_exposure):
            if value is not None and not nonnegative_number(value):
                return self._reject('Invalid configured risk maximum')
        if self._limits.max_order_value is None or self._limits.max_risk_per_order is None:
            return self._reject('Required risk maximum is missing')
        try:
            order_value = proposal.quantity * proposal.limit_price
            order_risk = proposal.quantity * abs(proposal.limit_price - proposal.stop_price) if proposal.stop_price is not None else 0
            if not all(math.isfinite(v) for v in (order_value, order_risk,
                    current_symbol_exposure + order_value, current_gross_exposure + order_value)):
                return self._reject('Risk arithmetic overflow')
        except OverflowError:
            return self._reject('Risk arithmetic overflow')
        from trading.production_paths import STATE_ROOT
        from reporting.telegram_gate import current
        try:
            control=current(STATE_ROOT)
            if control['revision']:
                caps=control['settings']
                order_value=proposal.quantity*proposal.limit_price
                measured={'max_quantity':proposal.quantity,'max_order_value':order_value,
                    'max_risk_per_order':proposal.quantity*abs(proposal.limit_price-proposal.stop_price) if proposal.stop_price is not None else None,
                    'max_symbol_exposure':current_symbol_exposure+order_value,'max_gross_exposure':current_gross_exposure+order_value}
                from decimal import Decimal
                for name,value in measured.items():
                    if value is not None and caps[name] is not None and Decimal(str(value))>Decimal(str(caps[name])):
                        return self._reject('Telegram additive cap exceeded: '+name+' revision '+str(control['revision']))
        except (OSError,ValueError,TypeError,KeyError,ArithmeticError):
            return self._reject('Telegram risk control is unreadable; fail closed')
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

        if (
            self._limits.max_symbol_exposure is not None
            and current_symbol_exposure + order_value > self._limits.max_symbol_exposure
        ):
            return self._reject("Symbol exposure exceeds the configured maximum")

        if (
            self._limits.max_gross_exposure is not None
            and current_gross_exposure + order_value > self._limits.max_gross_exposure
        ):
            return self._reject("Gross exposure exceeds the configured maximum")

        if proposal.stop_price is None:
            if self._limits.require_protective_stop:
                return self._reject("Protective stop is required")
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
