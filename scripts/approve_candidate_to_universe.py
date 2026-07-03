"""Approve a hard-audited candidate report into the local universe CSV.

This is the rule gate between LLM research and strategy modules. It refuses to
write when Python hard audit rejected the candidate.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.candidate_research import CandidateReport, load_candidate_report
from trading.universe import DEFAULT_UNIVERSE_FILE


FIELDNAMES = [
    "symbol",
    "name",
    "exchange",
    "sector",
    "enabled",
    "tags",
    "average_volume",
    "pe_ratio",
    "forward_pe",
    "peg_ratio",
    "debt_to_equity",
    "revenue_growth_yoy",
    "gross_margin",
    "operating_margin",
    "return_on_invested_capital",
    "free_cash_flow_positive",
    "earnings_positive",
    "analyst_revision_positive",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--approved-by", default="rules")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = load_candidate_report(args.report)
    if not report.hard_audit.approved:
        raise RuntimeError(
            "candidate report is not approved by Python hard audit: "
            + ", ".join(report.hard_audit.reasons)
        )
    rows = read_rows(args.universe_file)
    next_rows = upsert_candidate(rows, report, args.approved_by)
    payload = {
        "approved": True,
        "dry_run": args.dry_run,
        "symbol": report.symbol.upper(),
        "universe_file": str(args.universe_file),
        "row_count_before": len(rows),
        "row_count_after": len(next_rows),
        "approved_by": args.approved_by,
    }
    if not args.dry_run:
        write_rows(args.universe_file, next_rows)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_rows(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def upsert_candidate(
    rows: List[Dict[str, str]],
    report: CandidateReport,
    approved_by: str,
) -> List[Dict[str, str]]:
    symbol = report.symbol.upper()
    candidate_row = row_from_report(report, approved_by)
    next_rows = []
    replaced = False
    for row in rows:
        if row.get("symbol", "").upper() == symbol:
            merged = dict(row)
            merged.update({key: value for key, value in candidate_row.items() if value != ""})
            merged["enabled"] = "true"
            next_rows.append(merged)
            replaced = True
        else:
            next_rows.append(row)
    if not replaced:
        next_rows.append(candidate_row)
    return next_rows


def row_from_report(report: CandidateReport, approved_by: str) -> Dict[str, str]:
    draft = report.draft
    profile = draft.profile
    tags = list(draft.tags)
    tags.extend(["llm-reviewed", f"approved-by-{approved_by}"])
    return {
        "symbol": report.symbol.upper(),
        "name": draft.name,
        "exchange": draft.exchange,
        "sector": draft.sector,
        "enabled": "true",
        "tags": ";".join(dict.fromkeys(tag for tag in tags if tag)),
        "average_volume": "" if profile is None or profile.average_volume is None else str(profile.average_volume),
        "pe_ratio": "" if profile is None or profile.pe_ratio is None else str(profile.pe_ratio),
        "forward_pe": "" if profile is None or profile.forward_pe is None else str(profile.forward_pe),
        "peg_ratio": "" if profile is None or profile.peg_ratio is None else str(profile.peg_ratio),
        "debt_to_equity": "" if profile is None or profile.debt_to_equity is None else str(profile.debt_to_equity),
        "revenue_growth_yoy": "" if profile is None or profile.revenue_growth_yoy is None else str(profile.revenue_growth_yoy),
        "gross_margin": "" if profile is None or profile.gross_margin is None else str(profile.gross_margin),
        "operating_margin": "" if profile is None or profile.operating_margin is None else str(profile.operating_margin),
        "return_on_invested_capital": ""
        if profile is None or profile.return_on_invested_capital is None
        else str(profile.return_on_invested_capital),
        "free_cash_flow_positive": "true" if profile is None or profile.free_cash_flow_positive else "false",
        "earnings_positive": "true" if profile is None or profile.earnings_positive else "false",
        "analyst_revision_positive": ""
        if profile is None or profile.analyst_revision_positive is None
        else ("true" if profile.analyst_revision_positive else "false"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
