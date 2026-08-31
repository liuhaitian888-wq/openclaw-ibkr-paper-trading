#!/usr/bin/env python3
"""Read-only IBKR Level 1 streaming capability audit.

This script never places, modifies, or cancels orders. It only requests
contract details and Level 1 market data subscriptions, then cancels market
data subscriptions cleanly.
"""

import argparse
import csv
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from trading.config import Settings


REPORT_DIR = PROJECT_ROOT / "reports" / "market_data_capability"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMD", "IBM", "JPM", "KO", "SPY", "QQQ", "IWM")


class Level1AuditClient(EWrapper, EClient):
    def __init__(self, symbols: list[str], ticker_start: int = 81000) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.contract_ready = threading.Event()
        self.symbols = symbols
        self.ticker_to_symbol = {ticker_start + i: symbol for i, symbol in enumerate(symbols)}
        self.contract_req_to_symbol = {ticker_start + 1000 + i: symbol for i, symbol in enumerate(symbols)}
        self.rows: dict[str, dict[str, Any]] = {
            symbol: {
                "symbol": symbol,
                "contract_ok": False,
                "conid": None,
                "exchange": None,
                "primaryExchange": None,
                "marketDataType": None,
                "bid": None,
                "ask": None,
                "last": None,
                "close": None,
                "volume": None,
                "first_tick_latency": None,
                "update_count": 0,
                "last_tick_timestamp": None,
                "live_or_delayed": None,
                "stale_quote": True,
                "no_permission": False,
                "pacing_error": False,
                "errors": [],
            }
            for symbol in symbols
        }
        self.started_at: dict[int, float] = {}
        self.contract_end_count = 0
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def contractDetails(self, reqId: int, contractDetails: object) -> None:  # noqa: N802
        symbol = self.contract_req_to_symbol.get(reqId)
        if not symbol:
            return
        contract = getattr(contractDetails, "contract", None)
        row = self.rows[symbol]
        row["contract_ok"] = True
        row["conid"] = getattr(contract, "conId", None)
        row["exchange"] = getattr(contract, "exchange", None)
        row["primaryExchange"] = getattr(contract, "primaryExchange", None)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.contract_end_count += 1
        if self.contract_end_count >= len(self.symbols):
            self.contract_ready.set()

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802,N803
        row = self._row(reqId)
        if row is None:
            return
        row["marketDataType"] = int(marketDataType)
        row["live_or_delayed"] = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}.get(int(marketDataType), str(marketDataType))

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: object) -> None:  # noqa: N802
        if price <= 0:
            return
        row = self._row(reqId)
        if row is None:
            return
        field = {1: "bid", 2: "ask", 4: "last", 9: "close", 66: "bid", 67: "ask", 68: "last", 75: "close"}.get(tickType)
        if field is None:
            return
        if row["first_tick_latency"] is None and reqId in self.started_at:
            row["first_tick_latency"] = round((time.monotonic() - self.started_at[reqId]) * 1000, 3)
        row[field] = float(price)
        row["update_count"] += 1
        row["last_tick_timestamp"] = datetime.now(timezone.utc).isoformat()
        row["stale_quote"] = False

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        row = self._row(reqId)
        if row is not None and tickType in {8, 74}:
            row["volume"] = int(size)

    def error(self, reqId: int, *args: object) -> None:
        message = f"request={reqId}, details={args}"
        if any("connection is OK" in str(item) for item in args):
            return
        self.errors.append(message)
        row = self._row(reqId)
        if row is not None:
            row["errors"].append(message)
            text = message.lower()
            row["no_permission"] = row["no_permission"] or "permission" in text or "not subscribed" in text
            row["pacing_error"] = row["pacing_error"] or "pacing" in text or "max rate" in text

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS level1 audit thread stopped during disconnect: {exc}")
                return
            raise

    def _row(self, reqId: int) -> dict[str, Any] | None:
        symbol = self.ticker_to_symbol.get(reqId)
        return None if symbol is None else self.rows[symbol]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--client-id", type=int, default=68100)
    parser.add_argument("--market-data-type", type=int, default=1)
    parser.add_argument("--max-symbols", type=int, default=12)
    args = parser.parse_args()

    settings = Settings.load()
    symbols = list(dict.fromkeys(item.strip().upper() for item in args.symbols.split(",") if item.strip()))[: args.max_symbols]
    client = Level1AuditClient(symbols)
    try:
        client.connect(settings.tws_host, settings.tws_port, clientId=args.client_id)
        threading.Thread(target=client.run_loop, daemon=True).start()
        if not client.ready.wait(settings.tws_status_timeout):
            raise RuntimeError("TWS Level 1 audit handshake timed out")
        for req_id, symbol in client.contract_req_to_symbol.items():
            client.reqContractDetails(req_id, _stock_contract(symbol))
        client.contract_ready.wait(args.seconds)
        client.reqMarketDataType(args.market_data_type)
        for ticker_id, symbol in client.ticker_to_symbol.items():
            client.started_at[ticker_id] = time.monotonic()
            client.reqMktData(ticker_id, _stock_contract(symbol), "", False, False, [])
        time.sleep(args.seconds)
    finally:
        for ticker_id in getattr(client, "ticker_to_symbol", {}):
            try:
                client.cancelMktData(ticker_id)
            except Exception:
                pass
        if client.isConnected():
            client.disconnect()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "audit_ibkr_level1_streaming",
        "symbols": symbols,
        "rows": list(client.rows.values()),
        "errors": client.errors,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    with (REPORT_DIR / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(client.rows[symbols[0]].keys()) if symbols else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(client.rows.values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _stock_contract(symbol: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


if __name__ == "__main__":
    raise SystemExit(main())
