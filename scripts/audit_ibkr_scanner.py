#!/usr/bin/env python3
"""Read-only real IBKR market-scanner capability audit; never creates orders."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ibapi.client import EClient
from ibapi.scanner import ScannerSubscription
from ibapi.wrapper import EWrapper

from trading.config import Settings
from trading.paper_audit_db import insert_event


class ScannerAuditClient(EWrapper, EClient):
    def __init__(self, request_id: int) -> None:
        EClient.__init__(self, self)
        self.request_id = request_id
        self.ready = threading.Event()
        self.complete = threading.Event()
        self.rows: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def scannerData(self, reqId: int, rank: int, contractDetails: object, distance: str, benchmark: str, projection: str, legsStr: str) -> None:  # noqa: N802,E501
        contract = getattr(contractDetails, "contract", None)
        self.rows.append({
            "rank": int(rank), "symbol": getattr(contract, "symbol", ""), "conId": str(getattr(contract, "conId", "")),
            "exchange": getattr(contract, "exchange", ""), "primaryExchange": getattr(contract, "primaryExchange", ""),
            "currency": getattr(contract, "currency", ""), "secType": getattr(contract, "secType", ""),
            "distance": distance, "benchmark": benchmark, "projection": projection,
        })

    def scannerDataEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId == self.request_id:
            self.complete.set()

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        self.errors.append(f"request={reqId}, details={args}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-code", default="TOP_PERC_GAIN")
    parser.add_argument("--location", default="STK.US.MAJOR")
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--client-id", type=int, default=68500)
    args = parser.parse_args()
    settings = Settings.load()
    request_id = 68_500
    client = ScannerAuditClient(request_id)
    started = time.monotonic()
    try:
        client.connect(settings.tws_host, settings.tws_port, clientId=args.client_id)
        threading.Thread(target=client.run, daemon=True).start()
        if not client.ready.wait(args.timeout):
            raise RuntimeError("TWS scanner handshake timed out")
        subscription = ScannerSubscription()
        subscription.instrument = "STK"
        subscription.locationCode = args.location
        subscription.scanCode = args.scan_code
        subscription.numberOfRows = max(1, min(args.rows, 50))
        client.reqScannerSubscription(request_id, subscription, [], [])
        client.complete.wait(args.timeout)
    finally:
        try:
            client.cancelScannerSubscription(request_id)
        except Exception:
            pass
        if client.isConnected():
            client.disconnect()
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "source": "real_ibkr_scanner_audit",
        "scan_code": args.scan_code, "location": args.location, "row_count": len(client.rows),
        "latency_ms": round((time.monotonic() - started) * 1000, 3), "errors": client.errors,
        "rows": client.rows, "orders_submitted": 0, "scanner_subscription_cancelled": True,
    }
    report_dir = ROOT / "reports" / "ibkr_scanner"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    for row in client.rows:
        insert_event("ibkr_scanner_results", {"timestamp_utc": payload["timestamp_utc"], "discovery_run_id": f"real-scanner-{request_id}", "source_type": "IBKR_SCANNER_REAL", "scan_code": args.scan_code, **row, "raw_payload_ref": "IBKR_API", "included_in_discovery": 1, "blocked_reason": "read-only audit", "payload_json": json.dumps(row, sort_keys=True)})
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if client.rows and not client.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
