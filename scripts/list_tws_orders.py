"""List current TWS open orders and recent executions.

This command is read-only. It does not place, modify, or cancel orders.
"""

import argparse
import json
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ibapi.client import EClient
from ibapi.execution import ExecutionFilter
from ibapi.wrapper import EWrapper

from trading.config import Settings


class ReadOnlyOrdersClient(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.open_orders_ready = threading.Event()
        self.completed_orders_ready = threading.Event()
        self.executions_ready = threading.Event()
        self.next_order_id = None
        self.errors: List[str] = []
        self.open_orders: List[Dict[str, Any]] = []
        self.order_statuses: Dict[int, Dict[str, Any]] = {}
        self.executions: List[Dict[str, Any]] = []
        self.completed_orders: List[Dict[str, Any]] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.ready.set()

    def error(self, reqId: int, *args: object) -> None:
        self.errors.append(f"request={reqId}, details={args}")

    def openOrder(self, orderId: int, contract: object, order: object, orderState: object) -> None:  # noqa: N802,E501
        self.open_orders.append(
            {
                "order_id": orderId,
                "symbol": getattr(contract, "symbol", ""),
                "sec_type": getattr(contract, "secType", ""),
                "exchange": getattr(contract, "exchange", ""),
                "currency": getattr(contract, "currency", ""),
                "action": getattr(order, "action", ""),
                "order_type": getattr(order, "orderType", ""),
                "total_quantity": _number(getattr(order, "totalQuantity", None)),
                "limit_price": _number(getattr(order, "lmtPrice", None)),
                "aux_price": _number(getattr(order, "auxPrice", None)),
                "tif": getattr(order, "tif", ""),
                "transmit": getattr(order, "transmit", None),
                "outside_rth": getattr(order, "outsideRth", None),
                "order_ref": getattr(order, "orderRef", ""),
                "status": getattr(orderState, "status", ""),
                "warning_text": getattr(orderState, "warningText", ""),
            }
        )

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_orders_ready.set()

    def completedOrder(self, contract: object, order: object, orderState: object) -> None:  # noqa: N802,E501
        self.completed_orders.append(
            {
                "symbol": getattr(contract, "symbol", ""),
                "sec_type": getattr(contract, "secType", ""),
                "exchange": getattr(contract, "exchange", ""),
                "currency": getattr(contract, "currency", ""),
                "action": getattr(order, "action", ""),
                "order_type": getattr(order, "orderType", ""),
                "total_quantity": _number(getattr(order, "totalQuantity", None)),
                "limit_price": _number(getattr(order, "lmtPrice", None)),
                "aux_price": _number(getattr(order, "auxPrice", None)),
                "tif": getattr(order, "tif", ""),
                "transmit": getattr(order, "transmit", None),
                "outside_rth": getattr(order, "outsideRth", None),
                "order_ref": getattr(order, "orderRef", ""),
                "status": getattr(orderState, "status", ""),
                "completed_time": getattr(orderState, "completedTime", ""),
                "completed_status": getattr(orderState, "completedStatus", ""),
                "warning_text": getattr(orderState, "warningText", ""),
            }
        )

    def completedOrdersEnd(self) -> None:  # noqa: N802
        self.completed_orders_ready.set()

    def orderStatus(  # noqa: N802
        self,
        orderId: int,
        status: str,
        filled: Decimal,
        remaining: Decimal,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        self.order_statuses[orderId] = {
            "status": status,
            "filled": _number(filled),
            "remaining": _number(remaining),
            "avg_fill_price": avgFillPrice,
            "last_fill_price": lastFillPrice,
            "perm_id": permId,
            "parent_id": parentId,
            "client_id": clientId,
            "why_held": whyHeld,
        }

    def execDetails(self, reqId: int, contract: object, execution: object) -> None:  # noqa: N802,E501
        self.executions.append(
            {
                "req_id": reqId,
                "symbol": getattr(contract, "symbol", ""),
                "side": getattr(execution, "side", ""),
                "shares": _number(getattr(execution, "shares", None)),
                "price": _number(getattr(execution, "price", None)),
                "avg_price": _number(getattr(execution, "avgPrice", None)),
                "time": getattr(execution, "time", ""),
                "order_id": getattr(execution, "orderId", None),
                "client_id": getattr(execution, "clientId", None),
                "exec_id": getattr(execution, "execId", ""),
            }
        )

    def execDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.executions_ready.set()

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS client thread stopped during disconnect: {exc}")
                return
            raise


def _number(value: object) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=66001)
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    payload = read_tws_orders(
        host=args.host or settings.tws_host,
        port=args.port or settings.tws_port,
        client_id=args.client_id,
        timeout=args.timeout,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "ok" else 1


def read_tws_orders(
    *,
    host: str,
    port: int,
    client_id: int = 66001,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    client = ReadOnlyOrdersClient()
    started = time.perf_counter()
    try:
        client.connect(host, port, clientId=client_id)
        threading.Thread(target=client.run_loop, daemon=True).start()
        if not client.ready.wait(timeout):
            return {
                "status": "error",
                "error": "TWS API handshake timed out",
                "errors": client.errors,
            }

        client.reqAllOpenOrders()
        client.open_orders_ready.wait(timeout)

        try:
            client.reqCompletedOrders(False)
            client.completed_orders_ready.wait(timeout)
        except AttributeError:
            client.errors.append("reqCompletedOrders is unavailable in this ibapi version")

        client.reqExecutions(9001, ExecutionFilter())
        client.executions_ready.wait(timeout)

        return {
            "status": "ok",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "next_order_id": client.next_order_id,
            "open_order_count": len(client.open_orders),
            "open_orders": [
                {
                    **order,
                    "order_status": client.order_statuses.get(order["order_id"], {}),
                }
                for order in client.open_orders
            ],
            "completed_order_count": len(client.completed_orders),
            "completed_orders": client.completed_orders,
            "execution_count": len(client.executions),
            "executions": client.executions,
            "errors": client.errors,
        }
    finally:
        if client.isConnected():
            client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
