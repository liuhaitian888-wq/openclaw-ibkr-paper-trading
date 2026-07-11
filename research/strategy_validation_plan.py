import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.paper_validation_plan import (
    PaperValidationCandidate,
    PaperValidationPlan,
    submit_validate_payloads,
    write_plan,
)
from strategies.base import MarketData, PortfolioState, Signal
from strategies.dual_ma import DualMovingAverageStrategy
from strategies.grid import GridStrategy
from strategies.ml_baseline import LightGbmStyleBaselineStrategy


@dataclass(frozen=True)
class StrategyValidationPlanConfig:
    quotes_csv: Path
    output: Path = PROJECT_ROOT / "reports" / "paper_validation_plan.json"
    quantity: int = 1
    max_limit_price: float = 400.0
    max_spread_bps: float = 30.0
    min_confidence: float = 0.05
    grid_pct: float = 0.0002
    submit_validate: bool = False
    api_url: str = "http://127.0.0.1:8787"
    api_key: str = ""
    api_timeout: float = 20.0


def build_strategy_validation_plan(config: StrategyValidationPlanConfig) -> PaperValidationPlan:
    rows = _load_quote_rows(config.quotes_csv)
    grouped = _group_rows(rows)
    candidates: list[PaperValidationCandidate] = []
    for symbol, symbol_rows in grouped.items():
        market_data = _market_data_from_rows(symbol, symbol_rows)
        signals = _strategy_signals(market_data, grid_pct=config.grid_pct)
        candidates.extend(
            _candidate_from_signal(
                signal,
                market_data,
                quantity=config.quantity,
                max_limit_price=config.max_limit_price,
                max_spread_bps=config.max_spread_bps,
                min_confidence=config.min_confidence,
            )
            for signal in signals
        )
    plan = PaperValidationPlan(
        source="strategy_validation_plan",
        created_at=datetime.now(timezone.utc).isoformat(),
        diagnostics_path=str(config.quotes_csv),
        mode="validate_only",
        entry_z=0.0,
        quantity=config.quantity,
        candidate_count=len(candidates),
        validate_payload_count=sum(1 for candidate in candidates if candidate.validation_payload is not None),
        candidates=candidates,
    )
    if config.submit_validate:
        plan = submit_validate_payloads(
            plan,
            api_url=config.api_url,
            api_key=config.api_key,
            timeout=config.api_timeout,
        )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a validate-only plan from P0 strategy signals over recorded IBKR quotes. "
            "This script never places paper or live orders."
        )
    )
    parser.add_argument("--quotes-csv", type=Path, default=PROJECT_ROOT / "data" / "ibkr_quotes.csv")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_validation_plan.json")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--max-limit-price", type=float, default=400.0)
    parser.add_argument("--max-spread-bps", type=float, default=30.0)
    parser.add_argument("--min-confidence", type=float, default=0.05)
    parser.add_argument("--grid-pct", type=float, default=0.0002)
    parser.add_argument("--submit-validate", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=20.0)
    args = parser.parse_args()

    api_key = ""
    if args.submit_validate:
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    plan = build_strategy_validation_plan(
        StrategyValidationPlanConfig(
            quotes_csv=args.quotes_csv,
            output=args.output,
            quantity=args.quantity,
            max_limit_price=args.max_limit_price,
            max_spread_bps=args.max_spread_bps,
            min_confidence=args.min_confidence,
            grid_pct=args.grid_pct,
            submit_validate=args.submit_validate,
            api_url=args.api_url,
            api_key=api_key,
            api_timeout=args.api_timeout,
        )
    )
    write_plan(plan, args.output)
    print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    return 0


def _load_quote_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _group_rows(rows: Iterable[Mapping[str, str]]) -> dict[str, list[Mapping[str, str]]]:
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    return grouped


def _market_data_from_rows(symbol: str, rows: Sequence[Mapping[str, str]]) -> MarketData:
    prices = [_row_price(row) for row in rows]
    clean_prices = [price for price in prices if price > 0]
    if not clean_prices:
        raise ValueError(f"{symbol} has no usable prices")
    latest = rows[-1]
    first_price = clean_prices[0]
    last_price = clean_prices[-1]
    raw_return = (last_price - first_price) / first_price if first_price else 0.0
    probability = max(0.0, min(1.0, 0.5 + raw_return * 100.0))
    return MarketData(
        symbol=symbol,
        prices=clean_prices,
        timestamp=_parse_timestamp(str(latest.get("timestamp") or latest.get("requested_at") or "")),
        bid=_optional_float(latest.get("bid")),
        ask=_optional_float(latest.get("ask")),
        features={"ml_up_probability": probability},
    )


def _strategy_signals(market_data: MarketData, *, grid_pct: float) -> list[Signal]:
    prices = [float(price) for price in market_data.prices]
    portfolio = PortfolioState()
    signals: list[Signal] = []
    if len(prices) >= 10:
        signals.append(DualMovingAverageStrategy(fast_window=3, slow_window=10, target_quantity=1).generate_signal(market_data, portfolio))
    signals.append(GridStrategy(reference_price=prices[0], grid_pct=grid_pct, max_position=1).generate_signal(market_data, portfolio))
    signals.append(LightGbmStyleBaselineStrategy(target_quantity=1).generate_signal(market_data, portfolio))
    return signals


def _candidate_from_signal(
    signal: Signal,
    market_data: MarketData,
    *,
    quantity: int,
    max_limit_price: float,
    max_spread_bps: float,
    min_confidence: float,
) -> PaperValidationCandidate:
    limit_price = round(float(signal.limit_price or market_data.midpoint), 2)
    spread_bps = _spread_bps(market_data)
    payload: dict[str, Any] | None = None
    action = "WATCH"
    reason = signal.reason
    if signal.action == "HOLD":
        action = "WATCH"
    elif signal.action != "BUY":
        action = "WATCH"
        reason = f"{signal.strategy_name} produced {signal.action}; one-share gate currently accepts BUY smoke tests only"
    elif signal.confidence < min_confidence:
        action = "WATCH"
        reason = f"{signal.strategy_name} confidence {signal.confidence:.4f} is below {min_confidence:.4f}"
    elif limit_price <= 0 or limit_price > max_limit_price:
        action = "REJECT"
        reason = f"{signal.strategy_name} limit price {limit_price:.2f} exceeds max_limit_price {max_limit_price:.2f}"
    elif spread_bps is not None and spread_bps > max_spread_bps:
        action = "REJECT"
        reason = f"{signal.strategy_name} spread {spread_bps:.3f} bps exceeds max_spread_bps {max_spread_bps:.3f}"
    else:
        action = "VALIDATE_BUY_LIMIT"
        reason = f"{signal.strategy_name}: {signal.reason}"
        payload = _validation_payload(signal, quantity=quantity, limit_price=limit_price)

    return PaperValidationCandidate(
        symbol=signal.symbol,
        action=action,
        reason=reason,
        verdict="strategy_signal",
        score=round(float(signal.confidence) * 100.0, 6),
        latest_z_score=None,
        last_price=round(float(market_data.last), 6),
        validation_payload=payload,
    )


def _validation_payload(signal: Signal, *, quantity: int, limit_price: float) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return {
        "symbol": signal.symbol,
        "side": "BUY",
        "quantity": quantity,
        "limit_price": limit_price,
        "idempotency_key": f"validate-{signal.strategy_name[:18]}-{signal.symbol.lower()}-{timestamp}"[:64],
        "source": "strategy_validation_plan",
    }


def _row_price(row: Mapping[str, str]) -> float:
    for key in ("last", "close", "midpoint"):
        value = _optional_float(row.get(key))
        if value is not None and value > 0:
            return value
    bid = _optional_float(row.get("bid"))
    ask = _optional_float(row.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return 0.0


def _spread_bps(market_data: MarketData) -> float | None:
    if market_data.bid is None or market_data.ask is None or market_data.bid <= 0 or market_data.ask <= 0:
        return None
    midpoint = market_data.midpoint
    if midpoint <= 0:
        return None
    return ((market_data.ask - market_data.bid) / midpoint) * 10_000.0


def _parse_timestamp(raw: str) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
