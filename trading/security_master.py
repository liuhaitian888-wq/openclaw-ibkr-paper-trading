import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "security_master"
DEFAULT_UNIVERSE = PROJECT_ROOT / "data" / "us_equity_universe.csv"


@dataclass(frozen=True)
class SecurityMasterRecord:
    symbol: str
    company_name: str
    asset_type: str
    primary_exchange: str
    listing_exchange: str
    currency: str
    country: str
    sector: str
    industry: str
    is_etf: bool
    is_adr: bool
    is_otc: bool
    is_test_issue: bool
    financial_status: str
    listing_status: str
    CIK: str
    ibkr_conid: str
    data_source: str
    last_updated_at: str
    blocked_reason: str


def build_security_master_report(universe_file: Path = DEFAULT_UNIVERSE) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    records = [asdict(record) for record in load_seed_records(universe_file, now=now)]
    report = {
        "timestamp": now,
        "source": "security_master",
        "report_only": True,
        "data_sources": [str(universe_file)],
        "future_sources": ["Nasdaq Trader", "SEC company facts/submissions", "IBKR contractDetails"],
        "record_count": len(records),
        "records": records,
    }
    write_report(report)
    return report


def load_seed_records(universe_file: Path = DEFAULT_UNIVERSE, *, now: str | None = None) -> list[SecurityMasterRecord]:
    now = now or datetime.now(timezone.utc).isoformat()
    if not universe_file.exists():
        return []
    with universe_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [record_from_universe_row(row, now=now) for row in rows if row.get("symbol")]


def record_from_universe_row(row: Mapping[str, str], *, now: str) -> SecurityMasterRecord:
    symbol = str(row.get("symbol", "")).strip().upper()
    exchange = str(row.get("exchange", "")).strip().upper()
    tags = {item.strip().lower() for item in str(row.get("tags", "")).split(";") if item.strip()}
    is_etf = "etf" in tags or "index-etf" in tags or symbol in {"SPY", "QQQ", "IWM"}
    return SecurityMasterRecord(
        symbol=symbol,
        company_name=str(row.get("name", "")).strip(),
        asset_type="ETF" if is_etf else "STK",
        primary_exchange=exchange,
        listing_exchange=exchange,
        currency="USD",
        country="US",
        sector=str(row.get("sector", "")).strip(),
        industry="",
        is_etf=is_etf,
        is_adr="adr" in tags,
        is_otc=exchange in {"OTC", "PINK"},
        is_test_issue=False,
        financial_status="",
        listing_status="active" if str(row.get("enabled", "true")).lower() == "true" else "disabled",
        CIK="",
        ibkr_conid="",
        data_source="data/us_equity_universe.csv seed",
        last_updated_at=now,
        blocked_reason="" if str(row.get("enabled", "true")).lower() == "true" else "disabled in seed universe",
    )


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Security Master",
        "",
        f"- timestamp: {report.get('timestamp')}",
        f"- record_count: {report.get('record_count')}",
        f"- report_only: {report.get('report_only')}",
        "",
        "| Symbol | Name | Asset | Exchange | Sector | Source | Blocked |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report.get("records", [])[:200]:
        lines.append(
            f"| {row.get('symbol')} | {row.get('company_name')} | {row.get('asset_type')} | "
            f"{row.get('primary_exchange')} | {row.get('sector')} | {row.get('data_source')} | {row.get('blocked_reason')} |"
        )
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
