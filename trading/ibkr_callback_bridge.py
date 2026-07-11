"""REAL_IBKR callback bridge into logical realtime data buses."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from ibapi.client import EClient
from ibapi.common import TickerId
from ibapi.contract import Contract
from ibapi.execution import ExecutionFilter
from ibapi.execution import Execution
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.wrapper import EWrapper

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT, Settings
from trading.data_buses import MarketDataBus, build_data_bus_architecture_report
from trading.realtime_account_state_bus import RealtimeAccountStateBus
from trading.state_bootstrap_manager import StateBootstrapManager
from trading.state_timestamp_reconciler import TimestampReconciler
from trading.subscription_health import build_subscription_health_report


REPORT_DIR = PROJECT_ROOT / "reports" / "ibkr_callback_dry_run"


class IbkrCallbackBridge(EWrapper, EClient):
    def __init__(self, *, symbols_by_req_id: Mapping[int, str] | None = None, audit_writer: AuditWriter | None = None) -> None:
        EClient.__init__(self, self)
        self.audit_writer = audit_writer or AuditWriter()
        self.account_bus = RealtimeAccountStateBus(audit_writer=self.audit_writer)
        self.market_data_bus = MarketDataBus(self.account_bus)
        self.reconciler = TimestampReconciler(audit_writer=self.audit_writer)
        self.symbols_by_req_id = dict(symbols_by_req_id or {})
        self.ready = threading.Event()
        self.open_order_end = threading.Event()
        self.position_end = threading.Event()
        self.exec_details_end = threading.Event()
        self.connected_at = ""
        self.errors: list[str] = []
        self.callback_counts: dict[str, int] = {}
        self.last_event_seen_at: dict[str, str] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()
        self._record_callback("nextValidId", req_id=orderId, field_name="connection_state", raw_value=orderId, state_key="risk", payload={"next_valid_id": orderId})

    def connectionClosed(self) -> None:  # noqa: N802
        self._record_callback("connectionClosed", field_name="connection_state", raw_value="closed", state_key="risk", payload={"connection_closed": True}, stale_flag=True)

    def error(self, reqId: int, *args: object) -> None:
        message = "; ".join(str(arg) for arg in args)
        self.errors.append(f"request={reqId}, details={args}")
        event = self._base_event("error", req_id=reqId, field_name="error", raw_value=message)
        self.audit_writer.submit(
            "ibkr_error_events",
            {
                "event_id": event["event_id"],
                "timestamp_utc": event["processed_at"],
                "source_type": "REAL_IBKR",
                "callback_name": "error",
                "req_id": reqId,
                "error_code": int(args[0]) if args and str(args[0]).lstrip("-").isdigit() else None,
                "error_message": message,
                "state_version": event["state_version_after"],
                "payload_json": json.dumps(event, sort_keys=True, default=str),
            },
        )
        self.account_bus.update("risk", event, source_module="ibkr_callback_bridge", stale_flag=True)
        self._mark("error")

    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib: object) -> None:  # noqa: N802
        field = {1: "bid", 2: "ask", 4: "last", 9: "close"}.get(int(tickType), f"tick_price_{tickType}")
        self._record_callback("tickPrice", req_id=reqId, field_name=field, raw_value=price, normalized_value=float(price), state_key="quote", payload={"tick_type": tickType, field: float(price)})

    def tickSize(self, reqId: TickerId, tickType: int, size: Decimal) -> None:  # noqa: N802
        field = {0: "bid_size", 3: "ask_size", 8: "volume"}.get(int(tickType), f"tick_size_{tickType}")
        self._record_callback("tickSize", req_id=reqId, field_name=field, raw_value=size, normalized_value=float(size), state_key="quote", payload={"tick_type": tickType, field: float(size)})

    def tickString(self, reqId: TickerId, tickType: int, value: str) -> None:  # noqa: N802
        self._record_callback("tickString", req_id=reqId, field_name=f"tick_string_{tickType}", raw_value=value, normalized_value=value, state_key="quote", payload={"tick_type": tickType, "value": value})

    def tickGeneric(self, reqId: TickerId, tickType: int, value: float) -> None:  # noqa: N802
        self._record_callback("tickGeneric", req_id=reqId, field_name=f"tick_generic_{tickType}", raw_value=value, normalized_value=float(value), state_key="quote", payload={"tick_type": tickType, "value": float(value)})

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802,N803
        self._record_callback("marketDataType", req_id=reqId, field_name="market_data_type", raw_value=marketDataType, normalized_value=int(marketDataType), state_key="quote", payload={"market_data_type": int(marketDataType)})

    def tickReqParams(self, tickerId: int, minTick: float, bboExchange: str, snapshotPermissions: int) -> None:  # noqa: N802,N803
        self._record_callback("tickReqParams", req_id=tickerId, field_name="tick_req_params", raw_value=bboExchange, normalized_value=bboExchange, state_key="quote", payload={"min_tick": minTick, "bbo_exchange": bboExchange, "snapshot_permissions": snapshotPermissions})

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str) -> None:  # noqa: N802,N803
        self._record_callback("updateAccountValue", field_name=key, raw_value=val, normalized_value=val, state_key="account", payload={"key": key, "value": val, "currency": currency, "account": accountName})

    def updateAccountTime(self, timeStamp: str) -> None:  # noqa: N802,N803
        self._record_callback("updateAccountTime", field_name="account_time", raw_value=timeStamp, normalized_value=timeStamp, state_key="account", payload={"account_time": timeStamp})

    def accountDownloadEnd(self, accountName: str) -> None:  # noqa: N802,N803
        self._record_callback("accountDownloadEnd", field_name="account_download_end", raw_value=accountName, normalized_value=accountName, state_key="account", payload={"account": accountName})

    def updatePortfolio(self, contract: Contract, position: Decimal, marketPrice: float, marketValue: float, averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str) -> None:  # noqa: N802,E501,N803
        self._record_callback(
            "updatePortfolio",
            con_id=getattr(contract, "conId", None),
            symbol=getattr(contract, "symbol", ""),
            field_name="portfolio_position",
            raw_value=position,
            normalized_value=float(position),
            state_key="position",
            payload={"position": float(position), "market_price": marketPrice, "market_value": marketValue, "average_cost": averageCost, "unrealized_pnl": unrealizedPNL, "realized_pnl": realizedPNL, "account": accountName},
        )

    def position(self, account: str, contract: Contract, position: Decimal, avgCost: float) -> None:  # noqa: N802,N803
        self._record_callback("position", con_id=getattr(contract, "conId", None), symbol=getattr(contract, "symbol", ""), field_name="position", raw_value=position, normalized_value=float(position), state_key="position", payload={"account": account, "position": float(position), "avg_cost": avgCost})

    def positionEnd(self) -> None:  # noqa: N802
        self.position_end.set()
        self._record_callback("positionEnd", field_name="position_end", raw_value=True, normalized_value=True, state_key="position", payload={"position_end": True})

    def pnl(self, reqId: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float) -> None:  # noqa: N802,N803
        self._record_callback("pnl", req_id=reqId, field_name="account_pnl", raw_value=dailyPnL, normalized_value=float(dailyPnL), state_key="pnl", payload={"daily_pnl": dailyPnL, "unrealized_pnl": unrealizedPnL, "realized_pnl": realizedPnL})

    def pnlSingle(self, reqId: int, pos: Decimal, dailyPnL: float, unrealizedPnL: float, realizedPnL: float, value: float) -> None:  # noqa: N802,N803,E501
        self._record_callback("pnlSingle", req_id=reqId, field_name="position_pnl", raw_value=dailyPnL, normalized_value=float(dailyPnL), state_key="pnl", payload={"position": float(pos), "daily_pnl": dailyPnL, "unrealized_pnl": unrealizedPnL, "realized_pnl": realizedPnL, "value": value})

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState) -> None:  # noqa: N802,E501
        self._record_callback("openOrder", req_id=orderId, con_id=getattr(contract, "conId", None), symbol=getattr(contract, "symbol", ""), field_name="open_order", raw_value=getattr(order, "action", ""), normalized_value=getattr(orderState, "status", ""), state_key="open_order", payload={"order_id": orderId, "action": getattr(order, "action", ""), "order_type": getattr(order, "orderType", ""), "status": getattr(orderState, "status", "")})

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_order_end.set()
        self._record_callback("openOrderEnd", field_name="open_order_end", raw_value=True, normalized_value=True, state_key="open_order", payload={"open_order_end": True})

    def orderStatus(self, orderId: int, status: str, filled: Decimal, remaining: Decimal, avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float) -> None:  # noqa: N802,E501,N803
        self._record_callback("orderStatus", req_id=orderId, field_name="order_status", raw_value=status, normalized_value=status, state_key="open_order", payload={"order_id": orderId, "status": status, "filled": float(filled), "remaining": float(remaining), "avg_fill_price": avgFillPrice, "last_fill_price": lastFillPrice})

    def execDetails(self, reqId: int, contract: Contract, execution: Execution) -> None:  # noqa: N802
        self._record_callback("execDetails", req_id=reqId, con_id=getattr(contract, "conId", None), symbol=getattr(contract, "symbol", ""), field_name="execution", raw_value=getattr(execution, "execId", ""), normalized_value=getattr(execution, "execId", ""), state_key="execution", payload={"exec_id": getattr(execution, "execId", ""), "side": getattr(execution, "side", ""), "shares": float(getattr(execution, "shares", 0) or 0), "price": float(getattr(execution, "price", 0) or 0)})

    def execDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.exec_details_end.set()
        self._record_callback("execDetailsEnd", req_id=reqId, field_name="execution_end", raw_value=True, normalized_value=True, state_key="execution", payload={"exec_details_end": True})

    def commissionReport(self, commissionReport: object) -> None:  # noqa: N802,N803
        event = self._record_callback("commissionReport", field_name="commission", raw_value=getattr(commissionReport, "commission", None), normalized_value=getattr(commissionReport, "commission", None), state_key="execution", payload={"commission": getattr(commissionReport, "commission", None), "currency": getattr(commissionReport, "currency", ""), "realized_pnl": getattr(commissionReport, "realizedPNL", None)})
        self.audit_writer.submit(
            "commission_events",
            {
                "event_id": event["event_id"],
                "timestamp_utc": event["processed_at"],
                "source_type": "REAL_IBKR",
                "callback_name": "commissionReport",
                "commission": getattr(commissionReport, "commission", None),
                "currency": getattr(commissionReport, "currency", ""),
                "realized_pnl": getattr(commissionReport, "realizedPNL", None),
                "state_version": event["state_version_after"],
                "payload_json": json.dumps(event, sort_keys=True, default=str),
            },
        )

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError:
            return

    def _record_callback(
        self,
        callback_name: str,
        *,
        req_id: int | None = None,
        con_id: int | None = None,
        symbol: str = "",
        field_name: str,
        raw_value: Any,
        normalized_value: Any = None,
        state_key: str,
        payload: Mapping[str, Any],
        stale_flag: bool = False,
    ) -> dict[str, Any]:
        event = self._base_event(callback_name, req_id=req_id, con_id=con_id, symbol=symbol or self.symbols_by_req_id.get(req_id or -1, ""), field_name=field_name, raw_value=raw_value, normalized_value=normalized_value)
        before = self.account_bus.state_version
        bus_payload = {**event, **dict(payload), "source_type": "REAL_IBKR", "freshness_status": "FRESH" if not stale_flag else "STALE_BUT_LISTENING"}
        if state_key == "quote":
            self.market_data_bus.update_quote(bus_payload, source_module="ibkr_callback_bridge")
        else:
            self.account_bus.update(state_key, bus_payload, source_module="ibkr_callback_bridge", stale_flag=stale_flag)
        event["state_version_before"] = before
        event["state_version_after"] = self.account_bus.state_version
        self.reconciler.reconcile(field_name=field_name, value=normalized_value, symbol=event["symbol"], source_type="REAL_IBKR", source_timestamp=event["source_timestamp"], stale_threshold_sec=2.0)
        self.audit_writer.submit(
            "callback_wiring_events",
            {
                "event_id": event["event_id"],
                "timestamp_utc": event["processed_at"],
                "source_type": "REAL_IBKR",
                "callback_name": callback_name,
                "source_module": "ibkr_callback_bridge",
                "logical_bus": "MarketDataBus" if state_key == "quote" else "RealtimeAccountStateBus",
                "event_type_written": f"{state_key}_state_events",
                "wired_to_realtime_bus": 1,
                "payload_json": json.dumps(event, sort_keys=True, default=str),
            },
        )
        self._mark(callback_name)
        return event

    def _base_event(self, callback_name: str, *, req_id: int | None = None, con_id: int | None = None, symbol: str = "", field_name: str, raw_value: Any, normalized_value: Any = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "event_id": f"real-ibkr-{callback_name}-{len(self.callback_counts) + sum(self.callback_counts.values()) + 1}",
            "source_type": "REAL_IBKR",
            "callback_name": callback_name,
            "source_timestamp": now,
            "received_at": now,
            "processed_at": now,
            "req_id": req_id,
            "conId": con_id,
            "symbol": symbol,
            "field_name": field_name,
            "raw_value": str(raw_value),
            "normalized_value": normalized_value,
            "state_version_before": self.account_bus.state_version,
            "state_version_after": self.account_bus.state_version,
            "freshness_age_sec": 0.0,
            "stale_flag": False,
        }

    def _mark(self, callback_name: str) -> None:
        self.callback_counts[callback_name] = self.callback_counts.get(callback_name, 0) + 1
        self.last_event_seen_at[callback_name] = datetime.now(timezone.utc).isoformat()


def run_ibkr_callback_dry_run(*, duration_seconds: float = 60.0, symbols: list[str] | None = None) -> dict[str, Any]:
    settings = Settings.load()
    writer = AuditWriter()
    bridge = IbkrCallbackBridge(audit_writer=writer, symbols_by_req_id={50_000 + i: symbol for i, symbol in enumerate(symbols or [])})
    bootstrap = StateBootstrapManager(bridge.account_bus, audit_writer=writer).bootstrap(start_real_ibkr_subscriptions=True)
    build_data_bus_architecture_report()
    connected = False
    requested: list[str] = []
    try:
        bridge.connect(settings.tws_host, settings.tws_port, clientId=settings.tws_client_id + 1770)
        thread = threading.Thread(target=bridge.run_loop, daemon=True)
        thread.start()
        connected = bridge.ready.wait(settings.tws_status_timeout)
        if connected:
            account = ""
            try:
                bridge.reqAccountUpdates(True, account)
                requested.append("reqAccountUpdates")
            except Exception as exc:  # noqa: BLE001
                bridge.errors.append(f"reqAccountUpdates failed: {exc}")
            try:
                bridge.reqPositions()
                requested.append("reqPositions")
            except Exception as exc:
                bridge.errors.append(f"reqPositions failed: {exc}")
            try:
                bridge.reqOpenOrders()
                requested.append("reqOpenOrders")
            except Exception as exc:
                bridge.errors.append(f"reqOpenOrders failed: {exc}")
            try:
                bridge.reqExecutions(9901, ExecutionFilter())
                requested.append("reqExecutions")
            except Exception as exc:
                bridge.errors.append(f"reqExecutions failed: {exc}")
            try:
                bridge.reqPnL(9902, account, "")
                requested.append("reqPnL")
            except Exception as exc:
                bridge.errors.append(f"reqPnL failed: {exc}")
            for index, symbol in enumerate(symbols or []):
                try:
                    bridge.reqMktData(50_000 + index, stock_contract(symbol), "", False, False, [])
                    requested.append(f"reqMktData:{symbol}:snapshot=false:regulatorySnapshot=false")
                except Exception as exc:
                    bridge.errors.append(f"reqMktData failed for {symbol}: {exc}")
            if duration_seconds > 0:
                time.sleep(duration_seconds)
    except Exception as exc:
        bridge.errors.append(f"connect failed: {exc}")
    finally:
        try:
            if bridge.isConnected():
                try:
                    bridge.reqAccountUpdates(False, "")
                except Exception:
                    pass
                bridge.disconnect()
        except Exception:
            pass
    bridge.account_bus.write_report()
    bridge.reconciler.write_report()
    subscription = build_subscription_health_report(audit_writer=writer)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "ibkr_callback_dry_run",
        "duration_seconds": duration_seconds,
        "connected": connected,
        "callbacks_registered": True,
        "requested_streams": requested,
        "subscription_health": subscription,
        "bootstrap": bootstrap,
        "callback_counts": bridge.callback_counts,
        "last_event_seen_at": bridge.last_event_seen_at,
        "bus_status": "REAL_IBKR_ACTIVE" if any(bridge.callback_counts.values()) else "WAITING_FOR_REAL_IBKR" if connected else "DISCONNECTED",
        "snapshot_request_used": False,
        "regulatory_snapshot_used": False,
        "paid_snapshot_used": False,
        "orders_submitted": 0,
        "orders_cancelled": 0,
        "errors": bridge.errors,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        f"# IBKR Callback Dry Run\n\n- connected: {connected}\n- bus_status: {report['bus_status']}\n- snapshot_request_used: False\n- regulatory_snapshot_used: False\n- orders_submitted: 0\n",
        encoding="utf-8",
    )
    return report


def stock_contract(symbol: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract
