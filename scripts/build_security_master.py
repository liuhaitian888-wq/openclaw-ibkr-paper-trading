"""Build the persistent global security master.

This is a data-prep tool only. It does not connect to TWS, request market data,
or submit/cancel orders.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from trading.config import PROJECT_ROOT
from trading.security_master import records_from_nasdaq_trader_rows


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "security_master.csv"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--nasdaq-listed", type=Path)
    parser.add_argument("--other-listed", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    if args.download:
        rows.extend(load_nasdaq_trader_url(NASDAQ_LISTED_URL, source_name="nasdaqtrader:nasdaqlisted", now=now))
        rows.extend(load_nasdaq_trader_url(OTHER_LISTED_URL, source_name="nasdaqtrader:otherlisted", now=now))
    else:
        if args.nasdaq_listed:
            rows.extend(load_nasdaq_trader_file(args.nasdaq_listed, source_name=str(args.nasdaq_listed), now=now))
        if args.other_listed:
            rows.extend(load_nasdaq_trader_file(args.other_listed, source_name=str(args.other_listed), now=now))
    if not rows:
        raise SystemExit("no security master rows loaded; pass --download or input files")

    deduped = {}
    for row in rows:
        deduped.setdefault(row.symbol, row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_records(args.output, list(deduped.values()))
    print(f"wrote {len(deduped)} symbols to {args.output}")
    return 0


def load_nasdaq_trader_url(url: str, *, source_name: str, now: str) -> list:
    with urllib.request.urlopen(url, timeout=20) as response:
        text = response.read().decode("utf-8", errors="replace")
    return parse_pipe_text(text, source_name=source_name, now=now)


def load_nasdaq_trader_file(path: Path, *, source_name: str, now: str) -> list:
    return parse_pipe_text(path.read_text(encoding="utf-8"), source_name=source_name, now=now)


def parse_pipe_text(text: str, *, source_name: str, now: str) -> list:
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")
    return records_from_nasdaq_trader_rows(list(reader), source_name=source_name, now=now)


def write_records(path: Path, records: list) -> None:
    fieldnames = [
        "symbol",
        "company_name",
        "asset_type",
        "primary_exchange",
        "listing_exchange",
        "currency",
        "country",
        "sector",
        "industry",
        "is_etf",
        "is_adr",
        "is_otc",
        "is_test_issue",
        "financial_status",
        "listing_status",
        "CIK",
        "ibkr_conid",
        "data_source",
        "last_updated_at",
        "blocked_reason",
        "enabled",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item.symbol):
            row = asdict(record)
            row["enabled"] = not bool(record.blocked_reason)
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
