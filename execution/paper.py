from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from risk.core import OrderRiskConfig
from strategies.base import Signal


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    action: str
    quantity: int
    limit_price: float
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""


def paper_order(signal: Signal, current_position: int = 0) -> PaperOrder:
    if signal.action == "HOLD":
        raise ValueError("cannot create a paper order from a HOLD signal")
    if signal.limit_price is None:
        raise ValueError("paper order requires a limit price")
    quantity = abs(signal.target_position - current_position)
    if quantity <= 0:
        raise ValueError("paper order requires a non-zero position change")
    return PaperOrder(
        order_id=f"paper-{uuid4()}",
        symbol=signal.symbol.upper(),
        action=signal.action,
        quantity=quantity,
        limit_price=round(float(signal.limit_price), 2),
        status="PAPER_ACCEPTED",
        reason=signal.reason,
    )


def live_order(signal: Signal, risk_config: OrderRiskConfig) -> PaperOrder:
    if not risk_config.live_trading_enabled:
        raise PermissionError("live trading is disabled")
    if risk_config.kill_switch_enabled:
        raise PermissionError("live trading kill switch is enabled")
    raise NotImplementedError("live broker execution must be wired explicitly")
