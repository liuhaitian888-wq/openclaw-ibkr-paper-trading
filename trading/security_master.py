import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "security_master"
DEFAULT_UNIVERSE = PROJECT_ROOT / "data" / "us_equity_universe.csv"
DEFAULT_SECURITY_MASTER = PROJECT_ROOT / "data" / "security_master.csv"


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


def build_security_master_report(
    universe_file: Path = DEFAULT_UNIVERSE,
    *,
    security_master_file: Path = DEFAULT_SECURITY_MASTER,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    if security_master_file.exists():
        source_file = security_master_file
        records = [asdict(record) for record in load_security_master_records(security_master_file, now=now)]
        source_mode = "persistent_security_master"
    else:
        source_file = universe_file
        records = [asdict(record) for record in load_seed_records(universe_file, now=now)]
        source_mode = "seed_universe_fallback"
    report = {
        "timestamp": now,
        "source": "security_master",
        "report_only": True,
        "source_mode": source_mode,
        "data_sources": [str(source_file)],
        "future_sources": ["SEC company facts/submissions", "IBKR contractDetails"],
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


def load_security_master_records(path: Path = DEFAULT_SECURITY_MASTER, *, now: str | None = None) -> list[SecurityMasterRecord]:
    now = now or datetime.now(timezone.utc).isoformat()
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [record_from_security_master_row(row, now=now) for row in rows if row.get("symbol")]


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


def record_from_security_master_row(row: Mapping[str, str], *, now: str) -> SecurityMasterRecord:
    symbol = str(row.get("symbol", "")).strip().upper()
    exchange = str(row.get("primary_exchange") or row.get("exchange") or row.get("listing_exchange") or "").strip().upper()
    security_type = str(row.get("security_type") or row.get("asset_type") or "STK").strip().upper()
    enabled = str(row.get("enabled", "true")).lower() == "true"
    test_issue = str(row.get("is_test_issue", "false")).lower() == "true"
    etf = security_type == "ETF" or str(row.get("is_etf", "false")).lower() == "true"
    return SecurityMasterRecord(
        symbol=symbol,
        company_name=str(row.get("company_name") or row.get("name") or "").strip(),
        asset_type="ETF" if etf else security_type or "STK",
        primary_exchange=exchange,
        listing_exchange=str(row.get("listing_exchange") or exchange).strip().upper(),
        currency=str(row.get("currency") or "USD").strip().upper(),
        country=str(row.get("country") or "US").strip().upper(),
        sector=str(row.get("sector") or "").strip(),
        industry=str(row.get("industry") or "").strip(),
        is_etf=etf,
        is_adr=str(row.get("is_adr", "false")).lower() == "true",
        is_otc=exchange in {"OTC", "PINK"},
        is_test_issue=test_issue,
        financial_status=str(row.get("financial_status") or "").strip(),
        listing_status=str(row.get("listing_status") or ("active" if enabled else "disabled")).strip().lower(),
        CIK=str(row.get("CIK") or row.get("cik") or "").strip(),
        ibkr_conid=str(row.get("ibkr_conid") or "").strip(),
        data_source=str(row.get("data_source") or "data/security_master.csv").strip(),
        last_updated_at=str(row.get("last_updated_at") or now).strip(),
        blocked_reason=str(row.get("blocked_reason") or ("" if enabled and not test_issue else "disabled or test issue")).strip(),
    )


def records_from_nasdaq_trader_rows(rows: list[Mapping[str, str]], *, source_name: str, now: str | None = None) -> list[SecurityMasterRecord]:
    now = now or datetime.now(timezone.utc).isoformat()
    records: list[SecurityMasterRecord] = []
    for row in rows:
        symbol = str(row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
        if not symbol or symbol == "File Creation Time":
            continue
        name = str(row.get("Security Name") or row.get("Security Name") or "").strip()
        exchange = exchange_name(str(row.get("Exchange") or "NASDAQ"))
        etf = str(row.get("ETF") or "N").upper() == "Y"
        test_issue = str(row.get("Test Issue") or "N").upper() == "Y"
        status = str(row.get("Financial Status") or "").strip()
        records.append(
            SecurityMasterRecord(
                symbol=symbol,
                company_name=name,
                asset_type="ETF" if etf else "STK",
                primary_exchange=exchange,
                listing_exchange=exchange,
                currency="USD",
                country="US",
                sector="",
                industry="",
                is_etf=etf,
                is_adr=False,
                is_otc=exchange in {"OTC", "PINK"},
                is_test_issue=test_issue,
                financial_status=status,
                listing_status="active",
                CIK="",
                ibkr_conid="",
                data_source=source_name,
                last_updated_at=now,
                blocked_reason="test issue" if test_issue else "",
            )
        )
    return records


def exchange_name(value: str) -> str:
    return {
        "A": "NYSE_AMERICAN",
        "N": "NYSE",
        "P": "NYSE_ARCA",
        "Z": "BATS",
        "V": "IEX",
        "NASDAQ": "NASDAQ",
    }.get(value.upper(), value.upper())


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
