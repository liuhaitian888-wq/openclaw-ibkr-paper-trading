"""Build a Python hard-audit report from an OpenClaw/Gemini candidate draft.

This script does not place orders and does not update the trading universe. It
turns an agent/LLM proposal into an auditable candidate report that later rules
or a human can approve.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.candidate_research import (
    HardAuditConfig,
    build_candidate_report,
    load_candidate_draft,
    write_candidate_report,
)
from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import Quote
from trading.universe import DEFAULT_UNIVERSE_FILE, load_universe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path, help="OpenClaw/Gemini candidate JSON draft")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "candidates")
    parser.add_argument("--min-llm-confidence", type=float, default=0.6)
    parser.add_argument("--min-evidence-items", type=int, default=2)
    parser.add_argument("--min-value-score", type=float, default=45.0)
    parser.add_argument("--min-average-volume", type=int, default=1_000_000)
    parser.add_argument("--max-quote-age-ms", type=float, default=10_000.0)
    parser.add_argument("--max-spread-pct", type=float, default=0.003)
    parser.add_argument("--skip-contract-check", action="store_true")
    parser.add_argument("--skip-quote-check", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=4300)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--market-data-type", type=int, default=1)
    parser.add_argument("--exchange", default="SMART")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    draft = load_candidate_draft(args.draft)
    quote = None if args.skip_quote_check else fetch_quote(args, draft.symbol)
    contract_verified = args.skip_contract_check or quote is not None
    report = build_candidate_report(
        draft,
        existing_universe=load_universe(args.universe_file),
        config=HardAuditConfig(
            min_llm_confidence=args.min_llm_confidence,
            min_evidence_items=args.min_evidence_items,
            min_value_score=args.min_value_score,
            min_average_volume=args.min_average_volume,
            max_quote_age_ms=args.max_quote_age_ms,
            max_spread_pct=args.max_spread_pct,
            require_contract_verified=not args.skip_contract_check,
            require_realtime_quote=not args.skip_quote_check,
        ),
        quote=quote,
        contract_verified=contract_verified,
    )
    path = write_candidate_report(report, args.output_dir)
    payload = report.as_dict()
    payload["report_path"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.hard_audit.approved else 2


def fetch_quote(args: argparse.Namespace, symbol: str) -> Optional[Quote]:
    settings = Settings.load()
    source = IbkrReadOnlyQuoteSource(
        host=args.host or settings.tws_host,
        port=args.port or settings.tws_port,
        client_id=args.client_id,
        timeout=args.quote_timeout,
        snapshot=True,
        market_data_type=args.market_data_type,
        exchange=args.exchange,
    )
    quotes = source.get_quotes([symbol])
    return quotes[0] if quotes else None


if __name__ == "__main__":
    raise SystemExit(main())
