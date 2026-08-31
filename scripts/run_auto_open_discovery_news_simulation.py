#!/usr/bin/env python3
"""Run auto-open discovery/news/dynamic-pool/local-simulation pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.auto_open_pipeline import PipelineConfig, run_auto_open_pipeline


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "full"
    result = run_auto_open_pipeline(stage, config=PipelineConfig.from_env())
    print(
        json.dumps(
            {
                "status": "ok",
                "stage": stage,
                "run_id": result["run_id"],
                "final_audit": "reports/final_auto_open_discovery_news_simulation_audit/latest.json",
                "simulated_orders_count": result["simulation"].get("simulated_orders_count", 0),
                "ibkr_paper_orders_submitted": 0,
                "live_orders_submitted": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
