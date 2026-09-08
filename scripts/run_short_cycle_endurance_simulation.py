#!/usr/bin/env python3
"""Run the offline, no-broker short-cycle Paper endurance rehearsal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.production_paths import RUNTIME_ROOT

from trading.short_cycle_simulation import run_short_cycle_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RUNTIME_ROOT / "short_cycle_simulation")
    parser.add_argument("--cycles", type=int, default=8)
    args = parser.parse_args()
    summary = run_short_cycle_simulation(args.output_dir, cycles=args.cycles)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
