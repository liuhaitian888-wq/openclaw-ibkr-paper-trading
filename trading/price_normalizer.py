import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from trading.config import PROJECT_ROOT


OrderType = Literal["LMT", "STP", "STP LMT", "MKT"]
Side = Literal["BUY", "SELL"]
RoundingDirection = Literal["floor", "ceil", "nearest"]

DEFAULT_US_STOCK_MIN_TICK = Decimal("0.01")
REPORT_DIR = PROJECT_ROOT / "reports" / "price_normalizer"


@dataclass(frozen=True)
class PriceNormalization:
    timestamp: str
    symbol: str
    order_type: str
    side: str
    original_price: float
    normalized_price: float
    min_tick: float
    market_rule_id: str | None
    rounding_direction: str
    reason: str


def normalize_order_price(
    *,
    symbol: str,
    side: Side,
    order_type: OrderType,
    price: float,
    min_tick: float | Decimal | None = None,
    market_rule_id: str | None = None,
    log: bool = True,
) -> float:
    record = normalize_order_price_record(
        symbol=symbol,
        side=side,
        order_type=order_type,
        price=price,
        min_tick=min_tick,
        market_rule_id=market_rule_id,
    )
    if log:
        log_normalization(record)
    return record.normalized_price


def normalize_order_price_record(
    *,
    symbol: str,
    side: Side,
    order_type: OrderType,
    price: float,
    min_tick: float | Decimal | None = None,
    market_rule_id: str | None = None,
) -> PriceNormalization:
    tick = _decimal_tick(min_tick)
    original = Decimal(str(price))
    direction = rounding_direction(side=side, order_type=order_type)
    normalized = _round_to_tick(original, tick, direction)
    return PriceNormalization(
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol=symbol.strip().upper(),
        order_type=order_type,
        side=side,
        original_price=float(original),
        normalized_price=float(normalized),
        min_tick=float(tick),
        market_rule_id=market_rule_id,
        rounding_direction=direction,
        reason="normalized to valid minimum tick increment",
    )


def rounding_direction(*, side: Side, order_type: OrderType) -> RoundingDirection:
    if order_type == "LMT" and side == "BUY":
        return "floor"
    if order_type == "LMT" and side == "SELL":
        return "ceil"
    if order_type in {"STP", "STP LMT"} and side == "SELL":
        return "floor"
    if order_type in {"STP", "STP LMT"} and side == "BUY":
        return "ceil"
    return "nearest"


def log_normalization(record: PriceNormalization) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _decimal_tick(min_tick: float | Decimal | None) -> Decimal:
    if min_tick is None:
        return DEFAULT_US_STOCK_MIN_TICK
    tick = Decimal(str(min_tick))
    if tick <= 0:
        return DEFAULT_US_STOCK_MIN_TICK
    return tick


def _round_to_tick(price: Decimal, tick: Decimal, direction: RoundingDirection) -> Decimal:
    units = price / tick
    if direction == "floor":
        return (units.to_integral_value(rounding=ROUND_FLOOR) * tick).quantize(tick, rounding=ROUND_HALF_UP)
    if direction == "ceil":
        return (units.to_integral_value(rounding=ROUND_CEILING) * tick).quantize(tick, rounding=ROUND_HALF_UP)
    return (units.to_integral_value(rounding=ROUND_HALF_UP) * tick).quantize(tick, rounding=ROUND_HALF_UP)
