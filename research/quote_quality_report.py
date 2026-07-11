import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class SymbolQuoteQuality:
    symbol: str
    rows: int
    first_last: float
    final_last: float
    unique_last_count: int
    last_change_count: int
    total_abs_last_move: float
    average_spread: float | None
    max_spread: float | None
    average_relative_spread_bps: float | None
    volume_change_count: int
    verdict: str
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QuoteQualityReport:
    source: str
    created_at: str
    status: str
    csv_path: str
    total_rows: int
    symbols: list[SymbolQuoteQuality] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


def build_quote_quality_report(csv_path: Path) -> QuoteQualityReport:
    rows = _read_rows(csv_path)
    by_symbol: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if symbol:
            by_symbol.setdefault(symbol, []).append(row)
    symbols = [_symbol_quality(symbol, symbol_rows) for symbol, symbol_rows in sorted(by_symbol.items())]
    status = _status(symbols)
    return QuoteQualityReport(
        source="quote_quality_report",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        csv_path=str(csv_path),
        total_rows=len(rows),
        symbols=symbols,
        next_actions=_next_actions(status, symbols),
    )


def write_quote_quality_json(report: QuoteQualityReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_quote_quality_markdown(report: QuoteQualityReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    return output


def render_markdown(report: QuoteQualityReport) -> str:
    lines = [
        "# Quote Quality Report",
        "",
        f"Generated: `{report.created_at}`",
        "",
        f"Status: `{report.status}`",
        "",
        f"CSV: `{report.csv_path}`",
        "",
        f"Total rows: `{report.total_rows}`",
        "",
        "## Symbols",
        "",
    ]
    for symbol in report.symbols:
        lines.extend(
            [
                f"### {symbol.symbol}",
                "",
                f"- Verdict: `{symbol.verdict}`",
                f"- Rows: `{symbol.rows}`",
                f"- Unique last prices: `{symbol.unique_last_count}`",
                f"- Last price changes: `{symbol.last_change_count}`",
                f"- Total absolute last move: `{symbol.total_abs_last_move}`",
                f"- Average spread: `{_format_optional(symbol.average_spread)}`",
                f"- Max spread: `{_format_optional(symbol.max_spread)}`",
                f"- Average relative spread bps: `{_format_optional(symbol.average_relative_spread_bps)}`",
                f"- Volume changes: `{symbol.volume_change_count}`",
                "",
                "Notes:",
            ]
        )
        lines.extend(f"- {note}" for note in symbol.notes)
        lines.append("")
    lines.extend(["## Next Actions", ""])
    lines.extend(f"{index}. {action}" for index, action in enumerate(report.next_actions, start=1))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess whether recorded IBKR quote samples are useful for candidate generation.")
    parser.add_argument("csv_path", type=Path, nargs="?", default=PROJECT_ROOT / "data" / "ibkr_quotes.csv")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "quote_quality_report.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "quote_quality_report.md")
    args = parser.parse_args()

    report = build_quote_quality_report(args.csv_path)
    write_quote_quality_json(report, args.output_json)
    write_quote_quality_markdown(report, args.output_md)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _symbol_quality(symbol: str, rows: list[Mapping[str, str]]) -> SymbolQuoteQuality:
    lasts = [_float(row.get("last") or row.get("close")) for row in rows]
    lasts = [value for value in lasts if value is not None and value > 0]
    spreads = [_float(row.get("spread")) for row in rows]
    spreads = [value for value in spreads if value is not None and value >= 0]
    volumes = [_float(row.get("volume")) for row in rows]
    volumes = [value for value in volumes if value is not None]

    if not lasts:
        return SymbolQuoteQuality(symbol, len(rows), 0.0, 0.0, 0, 0, 0.0, None, None, None, 0, "unusable", ["no positive last prices"])

    last_changes = sum(1 for previous, current in zip(lasts, lasts[1:]) if current != previous)
    total_move = sum(abs(current - previous) for previous, current in zip(lasts, lasts[1:]))
    avg_spread = mean(spreads) if spreads else None
    max_spread = max(spreads) if spreads else None
    avg_rel_spread = None
    if avg_spread is not None and mean(lasts) > 0:
        avg_rel_spread = (avg_spread / mean(lasts)) * 10000
    volume_changes = sum(1 for previous, current in zip(volumes, volumes[1:]) if current != previous)

    notes: list[str] = []
    verdict = "usable_for_research"
    if len(lasts) < 10:
        verdict = "too_few_samples"
        notes.append("need at least 10 rows per symbol for current diagnostics")
    if len(set(lasts)) <= 1:
        verdict = "static_last_price"
        notes.append("last price did not change during the sample window")
    if avg_rel_spread is not None and avg_rel_spread > 20:
        notes.append("average spread is wide for short-horizon execution tests")
    if volume_changes > 0 and len(set(lasts)) <= 1:
        notes.append("market data is updating in some fields, but last price is static")
    if not notes:
        notes.append("quote sample has enough rows and observable last-price movement")

    return SymbolQuoteQuality(
        symbol=symbol,
        rows=len(lasts),
        first_last=round(lasts[0], 6),
        final_last=round(lasts[-1], 6),
        unique_last_count=len(set(lasts)),
        last_change_count=last_changes,
        total_abs_last_move=round(total_move, 6),
        average_spread=None if avg_spread is None else round(avg_spread, 6),
        max_spread=None if max_spread is None else round(max_spread, 6),
        average_relative_spread_bps=None if avg_rel_spread is None else round(avg_rel_spread, 3),
        volume_change_count=volume_changes,
        verdict=verdict,
        notes=notes,
    )


def _status(symbols: Iterable[SymbolQuoteQuality]) -> str:
    items = list(symbols)
    if not items:
        return "no_quotes"
    if any(item.verdict == "usable_for_research" for item in items):
        return "usable_quote_movement_detected"
    if all(item.verdict == "static_last_price" for item in items):
        return "static_last_prices"
    return "quote_quality_attention_required"


def _next_actions(status: str, symbols: list[SymbolQuoteQuality]) -> list[str]:
    if status == "usable_quote_movement_detected":
        return ["Run guarded validate-only with the recorded sample.", "Inspect validation payloads and execution gate before any paper order."]
    if status == "static_last_prices":
        return [
            "Repeat collection during a more active market window or use real-time market data permissions if available.",
            "Increase sample duration before expecting mean-reversion diagnostics to produce a candidate.",
            "Do not force a paper order from static last-price samples.",
        ]
    if status == "no_quotes":
        return ["Confirm TWS market data permissions and rerun read-only quote capture."]
    return ["Review per-symbol notes and collect a cleaner quote sample before candidate generation."]


def _read_rows(path: Path) -> list[Mapping[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
