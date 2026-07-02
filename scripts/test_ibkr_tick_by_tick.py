"""Sample IBKR tick-by-tick read-only market data.

This command requests tick-by-tick data for one symbol and prints the raw event
shape returned by TWS. It does not place orders.
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings


class TickByTickClient(EWrapper, EClient):
    def __init__(self, max_events: int) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.errors: List[str] = []
        self.events: List[Dict[str, Any]] = []
        self.max_events = max_events

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        self.errors.append(f"request={reqId}, details={args}")

    def tickByTickAllLast(  # noqa: N802
        self,
        reqId: int,
        tickType: int,
        time: int,
        price: float,
        size: Decimal,
        tickAttribLast: object,
        exchange: str,
        specialConditions: str,
    ) -> None:
        self._append(
            {
                "event": "all_last",
                "req_id": reqId,
                "tick_type": tickType,
                "time": self._event_time(time),
                "price": float(price),
                "size": str(size),
                "exchange": exchange,
                "special_conditions": specialConditions,
                "attributes": str(tickAttribLast),
            }
        )

    def tickByTickBidAsk(  # noqa: N802
        self,
        reqId: int,
        time: int,
        bidPrice: float,
        askPrice: float,
        bidSize: Decimal,
        askSize: Decimal,
        tickAttribBidAsk: object,
    ) -> None:
        self._append(
            {
                "event": "bid_ask",
                "req_id": reqId,
                "time": self._event_time(time),
                "bid": float(bidPrice),
                "ask": float(askPrice),
                "bid_size": str(bidSize),
                "ask_size": str(askSize),
                "attributes": str(tickAttribBidAsk),
            }
        )

    def tickByTickMidPoint(self, reqId: int, time: int, midPoint: float) -> None:  # noqa: N802
        self._append(
            {
                "event": "midpoint",
                "req_id": reqId,
                "time": self._event_time(time),
                "midpoint": float(midPoint),
            }
        )

    def _append(self, event: Dict[str, Any]) -> None:
        event["received_at"] = datetime.now(timezone.utc).isoformat()
        self.events.append(event)
        if len(self.events) >= self.max_events:
            self.done.set()

    @staticmethod
    def _event_time(epoch_seconds: int) -> str:
        return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--tick-type", default="BidAsk", choices=("Last", "AllLast", "BidAsk", "MidPoint"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=910)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-events", type=int, default=10)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument(
        "--market-data-type",
        type=int,
        default=1,
        help="IBKR market data type: 1 real-time, 3 delayed, 4 delayed-frozen.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    client = TickByTickClient(max_events=args.max_events)
    req_id = 91_000
    host = args.host or settings.tws_host
    port = args.port or settings.tws_port

    try:
        client.connect(host, port, clientId=args.client_id)
        threading.Thread(target=client.run, daemon=True).start()
        if not client.ready.wait(args.timeout):
            print(json.dumps({"ok": False, "errors": client.errors + ["TWS API handshake timed out"]}, indent=2))
            return 2
        client.reqMarketDataType(args.market_data_type)
        client.reqTickByTickData(
            req_id,
            stock_contract(args.symbol, args.exchange),
            args.tick_type,
            0,
            False,
        )
        client.done.wait(args.timeout)
        payload = {
            "ok": bool(client.events),
            "symbol": args.symbol.upper(),
            "tick_type": args.tick_type,
            "market_data_type": args.market_data_type,
            "event_count": len(client.events),
            "errors": client.errors,
            "events": client.events,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if client.events else 1
    finally:
        try:
            client.cancelTickByTickData(req_id)
        except Exception:
            pass
        if client.isConnected():
            client.disconnect()


def stock_contract(symbol: str, exchange: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol.strip().upper()
    contract.secType = "STK"
    contract.exchange = exchange.strip().upper() or "SMART"
    contract.currency = "USD"
    return contract


if __name__ == "__main__":
    raise SystemExit(main())
