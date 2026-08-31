#!/usr/bin/env python3
"""Measure real concurrent L1 capacity incrementally and cancel every subscription."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_ibkr_level1_streaming import Level1AuditClient, _stock_contract
from trading.config import Settings
from trading.universe import default_universe_symbols


def measure(size: int, *, client_id: int, seconds: float) -> dict[str, object]:
    settings = Settings.load()
    symbols = default_universe_symbols()[:size]
    client = Level1AuditClient(symbols, ticker_start=90_000 + client_id)
    started = time.monotonic()
    try:
        client.connect(settings.tws_host, settings.tws_port, clientId=client_id)
        threading.Thread(target=client.run_loop, daemon=True).start()
        if not client.ready.wait(settings.tws_status_timeout):
            raise RuntimeError("TWS Level1 capacity handshake timed out")
        for req_id, symbol in client.contract_req_to_symbol.items():
            client.reqContractDetails(req_id, _stock_contract(symbol))
        client.contract_ready.wait(seconds)
        client.reqMarketDataType(1)
        for req_id, symbol in client.ticker_to_symbol.items():
            client.started_at[req_id] = time.monotonic()
            client.reqMktData(req_id, _stock_contract(symbol), "", False, False, [])
        time.sleep(seconds)
    finally:
        for req_id in getattr(client, "ticker_to_symbol", {}):
            try:
                client.cancelMktData(req_id)
            except Exception:
                pass
        if client.isConnected():
            client.disconnect()
    rows = list(client.rows.values())
    ticked = [row for row in rows if not row["stale_quote"]]
    errors = [*client.errors, *(error for row in rows for error in row["errors"])]
    return {
        "requested_lines": size, "ticked_lines": len(ticked), "errors": list(dict.fromkeys(errors)),
        "pacing_error": any(row["pacing_error"] for row in rows), "permission_error": any(row["no_permission"] for row in rows),
        "latency_ms": {row["symbol"]: row["first_tick_latency"] for row in rows},
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        "stable": len(ticked) == size and not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default="3,6,12,24,48")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--client-id-base", type=int, default=68600)
    args = parser.parse_args()
    runs = []
    for offset, raw in enumerate(args.steps.split(",")):
        size = int(raw.strip())
        result = measure(size, client_id=args.client_id_base + offset, seconds=args.seconds)
        runs.append(result)
        if not result["stable"]:
            break
    payload = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "source": "real_ibkr_l1_capacity", "runs": runs, "max_stable_lines_observed": max((int(row["requested_lines"]) for row in runs if row["stable"]), default=0), "orders_submitted": 0}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
