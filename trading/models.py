from dataclasses import dataclass
from typing import Literal, Optional


Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    side: Side
    quantity: int
    limit_price: float
    stop_price: Optional[float]
    idempotency_key: str = ""


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    status: Literal["APPROVED", "REJECTED"]
    reason: str
