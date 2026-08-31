import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class MeanReversionDiagnostics:
    adf_lag1_t_stat: Optional[float]
    half_life_periods: Optional[float]
    hurst_exponent: Optional[float]
    variance_ratio: Optional[float]
    latest_z_score: Optional[float]
    mean_reversion_score: float
    verdict: str
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class PriceDiagnostics:
    symbol: str
    created_at: str
    observation_count: int
    first_price: float
    last_price: float
    diagnostics: MeanReversionDiagnostics


def diagnose_prices(prices: Sequence[float], *, z_window: int = 20) -> MeanReversionDiagnostics:
    clean = [float(price) for price in prices if float(price) > 0 and math.isfinite(float(price))]
    notes: List[str] = []
    if len(clean) < 10:
        return MeanReversionDiagnostics(None, None, None, None, None, 0.0, "insufficient_data", ("need at least 10 positive prices",))

    adf_t = _lag1_adf_t_stat(clean)
    half_life = _half_life(clean)
    hurst = _hurst_exponent(clean)
    variance_ratio = _variance_ratio(clean, lag=min(5, max(2, len(clean) // 10)))
    z_score = _latest_z_score(clean, min(z_window, len(clean)))

    score = 0.0
    if adf_t is not None:
        if adf_t <= -3.0:
            score += 35.0
        elif adf_t <= -2.0:
            score += 20.0
        else:
            notes.append("lag-1 ADF-style t-stat is weak")
    if half_life is not None:
        if 1.0 <= half_life <= max(2.0, len(clean) / 3):
            score += 25.0
        else:
            notes.append("half-life is outside a practical trading range")
    if hurst is not None:
        if hurst < 0.45:
            score += 20.0
        elif hurst < 0.5:
            score += 10.0
        else:
            notes.append("Hurst exponent does not clearly indicate mean reversion")
    if variance_ratio is not None:
        if variance_ratio < 0.9:
            score += 20.0
        else:
            notes.append("variance ratio does not clearly indicate mean reversion")

    verdict = "reject"
    if score >= 70:
        verdict = "research_candidate"
    elif score >= 45:
        verdict = "watchlist"

    if not notes:
        notes.append("diagnostics are consistent with mean-reversion research")

    return MeanReversionDiagnostics(
        adf_lag1_t_stat=_round_optional(adf_t),
        half_life_periods=_round_optional(half_life),
        hurst_exponent=_round_optional(hurst),
        variance_ratio=_round_optional(variance_ratio),
        latest_z_score=_round_optional(z_score),
        mean_reversion_score=round(score, 3),
        verdict=verdict,
        notes=tuple(notes),
    )


def diagnose_symbol_prices(symbol: str, prices: Sequence[float], *, z_window: int = 20) -> PriceDiagnostics:
    clean = [float(price) for price in prices if float(price) > 0 and math.isfinite(float(price))]
    if not clean:
        raise ValueError("prices must contain at least one positive finite value")
    return PriceDiagnostics(
        symbol=symbol.upper(),
        created_at=datetime.now(timezone.utc).isoformat(),
        observation_count=len(clean),
        first_price=clean[0],
        last_price=clean[-1],
        diagnostics=diagnose_prices(clean, z_window=z_window),
    )


def read_prices_csv(path: Path, *, price_column: str = "close", symbol_column: str = "symbol") -> dict[str, List[float]]:
    by_symbol: dict[str, List[float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV must include a header")
        fields = {field.lower(): field for field in reader.fieldnames}
        actual_price = fields.get(price_column.lower())
        actual_symbol = fields.get(symbol_column.lower())
        if actual_price is None:
            raise ValueError(f"CSV is missing price column: {price_column}")
        for row_number, row in enumerate(reader, start=2):
            raw_price = row.get(actual_price, "").strip()
            if not raw_price:
                continue
            try:
                price = float(raw_price)
            except ValueError as exc:
                raise ValueError(f"invalid price on row {row_number}: {raw_price}") from exc
            symbol = row.get(actual_symbol, "SERIES") if actual_symbol else "SERIES"
            by_symbol.setdefault(symbol.strip().upper() or "SERIES", []).append(price)
    return by_symbol


def write_report(report: Iterable[PriceDiagnostics], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(item) for item in report]
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run lightweight Chan-style mean-reversion diagnostics on a price CSV.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--price-column", default="close")
    parser.add_argument("--symbol-column", default="symbol")
    parser.add_argument("--z-window", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("reports/mean_reversion_diagnostics.json"))
    args = parser.parse_args()

    symbol_prices = read_prices_csv(args.csv_path, price_column=args.price_column, symbol_column=args.symbol_column)
    report = [
        diagnose_symbol_prices(symbol, prices, z_window=args.z_window)
        for symbol, prices in sorted(symbol_prices.items())
    ]
    write_report(report, args.output)
    print(json.dumps([asdict(item) for item in report], indent=2, sort_keys=True))
    return 0


def _lag1_adf_t_stat(prices: Sequence[float]) -> Optional[float]:
    lagged = prices[:-1]
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    return _slope_t_stat(lagged, deltas)


def _half_life(prices: Sequence[float]) -> Optional[float]:
    lagged = prices[:-1]
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    slope = _ols_slope(lagged, deltas)
    if slope is None or slope >= 0:
        return None
    half_life = -math.log(2) / slope
    if not math.isfinite(half_life) or half_life <= 0:
        return None
    return half_life


def _hurst_exponent(prices: Sequence[float]) -> Optional[float]:
    max_lag = min(20, len(prices) // 2)
    if max_lag < 3:
        return None
    log_lags: List[float] = []
    log_tau: List[float] = []
    for lag in range(2, max_lag + 1):
        diffs = [prices[i] - prices[i - lag] for i in range(lag, len(prices))]
        tau = pstdev(diffs) if len(diffs) > 1 else 0.0
        if tau > 0:
            log_lags.append(math.log(lag))
            log_tau.append(math.log(tau))
    slope = _ols_slope(log_lags, log_tau)
    return slope if slope is not None and math.isfinite(slope) else None


def _variance_ratio(prices: Sequence[float], lag: int) -> Optional[float]:
    returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]
    if len(returns) <= lag or lag <= 1:
        return None
    one_period_var = _sample_variance(returns)
    lagged_returns = [
        sum(returns[index - lag + 1 : index + 1])
        for index in range(lag - 1, len(returns))
    ]
    lag_var = _sample_variance(lagged_returns)
    if one_period_var is None or lag_var is None or one_period_var <= 0:
        return None
    return lag_var / (lag * one_period_var)


def _latest_z_score(prices: Sequence[float], window: int) -> Optional[float]:
    if window < 2 or len(prices) < window:
        return None
    sample = prices[-window:]
    sigma = pstdev(sample)
    if sigma == 0:
        return None
    return (prices[-1] - mean(sample)) / sigma


def _ols_slope(x_values: Sequence[float], y_values: Sequence[float]) -> Optional[float]:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    if denominator == 0:
        return None
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    return numerator / denominator


def _slope_t_stat(x_values: Sequence[float], y_values: Sequence[float]) -> Optional[float]:
    slope = _ols_slope(x_values, y_values)
    if slope is None or len(x_values) < 3:
        return None
    intercept = mean(y_values) - slope * mean(x_values)
    residuals = [y - intercept - slope * x for x, y in zip(x_values, y_values)]
    sse = sum(residual * residual for residual in residuals)
    degrees = len(x_values) - 2
    x_mean = mean(x_values)
    x_sse = sum((x - x_mean) ** 2 for x in x_values)
    if degrees <= 0 or x_sse <= 0:
        return None
    slope_se = math.sqrt((sse / degrees) / x_sse)
    if slope_se == 0:
        return None
    return slope / slope_se


def _sample_variance(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    avg = mean(values)
    return sum((value - avg) ** 2 for value in values) / (len(values) - 1)


def _round_optional(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 6)


if __name__ == "__main__":
    raise SystemExit(main())
