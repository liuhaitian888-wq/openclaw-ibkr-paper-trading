"""Benchmark autonomous-agent cycle timings across universe sizes.

This uses the same Trading API health check and IBKR read-only quote source as
the autonomous agent, but disables the strategy subprocess so the result focuses
on supervisor, universe, and market-data latency.
"""

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_autonomous_trading_agent import DEFAULT_API_URL, read_required, run_cycle
from trading.config import Settings
from trading.universe import DEFAULT_UNIVERSE_FILE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--sizes", default="12,30,60")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--min-value-score", type=float, default=45.0)
    parser.add_argument("--client-id", type=int, default=8200)
    parser.add_argument("--ibkr-workers", type=int, default=8)
    parser.add_argument("--ibkr-symbols-per-worker", type=int, default=8)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--market-data-type", type=int, default=1)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "reports" / "autonomous_agent" / "benchmarks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    api_key = read_required(args.api_key_file, "OPENCLAW_API_KEY")
    settings = Settings.load()
    sizes = [int(value.strip()) for value in args.sizes.split(",") if value.strip()]
    all_results = []
    for size in sizes:
        sample_results = []
        state: Dict[str, Dict[str, float]] = {}
        for sample in range(1, args.samples + 1):
            cycle_args = argparse.Namespace(
                api_url=args.api_url,
                api_key_file=args.api_key_file,
                universe_file=args.universe_file,
                max_universe_symbols=size,
                min_value_score=args.min_value_score,
                strategy_every_cycles=0,
                disable_strategy=True,
                strategy_mode="validate",
                strategy_steps=0,
                strategy_max_orders=0,
                client_id=args.client_id + size * 10 + sample,
                ibkr_workers=args.ibkr_workers,
                ibkr_symbols_per_worker=args.ibkr_symbols_per_worker,
                quote_timeout=args.quote_timeout,
                market_data_type=args.market_data_type,
                exchange=args.exchange,
                report_dir=args.report_dir,
                candidate_inbox=PROJECT_ROOT / "reports" / "agent_research" / "inbox",
                candidate_auto_approve=False,
            )
            result = run_cycle(cycle_args, api_key, settings, state, sample)
            sample_results.append(result.as_dict())
        all_results.append(summarize_size(size, sample_results))

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sizes": sizes,
        "samples": args.samples,
        "results": all_results,
    }
    output_path = args.report_dir / f"cycle_benchmark_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(output_path), "results": all_results}, ensure_ascii=False, indent=2))
    return 0


def summarize_size(size: int, samples: List[Dict[str, object]]) -> Dict[str, object]:
    timing_keys = sorted(
        {
            key
            for sample in samples
            for key in (sample.get("timings", {}) if isinstance(sample.get("timings"), dict) else {})
        }
    )
    averages = {}
    p95 = {}
    for key in timing_keys:
        values = [
            float(sample["timings"][key])
            for sample in samples
            if isinstance(sample.get("timings"), dict) and key in sample["timings"]
        ]
        if not values:
            continue
        averages[key] = round(statistics.fmean(values), 3)
        p95_index = max(0, min(len(values) - 1, math.ceil(len(values) * 0.95) - 1))
        p95[key] = round(sorted(values)[p95_index], 3)
    return {
        "size": size,
        "sample_count": len(samples),
        "avg_ms": averages,
        "p95_ms": p95,
        "quote_counts": [sample.get("quote_count", 0) for sample in samples],
        "error_counts": [len(sample.get("errors", [])) for sample in samples],
    }


if __name__ == "__main__":
    raise SystemExit(main())
