from dataclasses import dataclass
from typing import FrozenSet

from strategies.base import PortfolioState, Signal


@dataclass(frozen=True)
class OrderRiskConfig:
    allowed_symbols: FrozenSet[str] = frozenset({"AAPL", "MSFT", "SPY"})
    max_order_quantity: int = 1
    max_order_value: float = 200.0
    max_gross_exposure: float = 1_200.0
    min_confidence: float = 0.0
    live_trading_enabled: bool = False
    kill_switch_enabled: bool = True


@dataclass(frozen=True)
class OrderRiskDecision:
    approved: bool
    reason: str


def validate_order(signal: Signal, portfolio_state: PortfolioState, risk_config: OrderRiskConfig) -> OrderRiskDecision:
    if signal.action == "HOLD":
        return OrderRiskDecision(True, "hold signal does not create an order")
    if risk_config.kill_switch_enabled:
        return OrderRiskDecision(False, "kill switch is enabled")
    if signal.symbol.upper() not in risk_config.allowed_symbols:
        return OrderRiskDecision(False, "symbol is not on the allowlist")
    if signal.confidence < risk_config.min_confidence:
        return OrderRiskDecision(False, "signal confidence is below minimum")
    quantity_delta = abs(signal.target_position - portfolio_state.position_for(signal.symbol))
    if quantity_delta <= 0:
        return OrderRiskDecision(False, "target position does not change current position")
    if quantity_delta > risk_config.max_order_quantity:
        return OrderRiskDecision(False, "order quantity exceeds limit")
    if signal.limit_price is None or signal.limit_price <= 0:
        return OrderRiskDecision(False, "signal requires a positive limit price")
    if quantity_delta * signal.limit_price > risk_config.max_order_value:
        return OrderRiskDecision(False, "order value exceeds limit")
    gross_after = portfolio_state.equity - portfolio_state.cash + quantity_delta * signal.limit_price
    if gross_after > risk_config.max_gross_exposure:
        return OrderRiskDecision(False, "gross exposure exceeds limit")
    return OrderRiskDecision(True, "risk checks passed")
