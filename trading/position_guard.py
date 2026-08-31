import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from trading.config import PROJECT_ROOT, Settings
from trading.ibkr_readonly import ParallelIbkrReadOnlyQuoteSource
from trading.market_data import Quote


REPORT_DIR = PROJECT_ROOT / "reports" / "position_guard"


@dataclass(frozen=True)
class PositionRecord:
    symbol: str
    position_qty: float
    avg_cost: float | None
    market_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None


@dataclass(frozen=True)
class ProtectionStatus:
    position_covered_by_stop: bool
    duplicate_stop_warning: bool
    missing_stop_warning: bool
    overprotected_warning: bool
    underprotected_warning: bool
    risk_action_needed: bool
    recommended_action: str


class ReadOnlyPositionsClient(EWrapper, EClient):
    def __init__(self, account: str = "") -> None:
        EClient.__init__(self, self)
        self.account = account
        self.ready = threading.Event()
        self.account_download_end = threading.Event()
        self.accounts: list[str] = []
        self.positions: dict[str, PositionRecord] = {}
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item for item in accountsList.split(",") if item]

    def updatePortfolio(  # noqa: N802
        self,
        contract: Contract,
        position: float,
        marketPrice: float,
        marketValue: float,
        averageCost: float,
        unrealizedPNL: float,
        realizedPNL: float,
        accountName: str,
    ) -> None:
        if self.account and accountName != self.account:
            return
        symbol = str(contract.symbol or "").upper()
        if not symbol or position == 0:
            return
        self.positions[symbol] = PositionRecord(
            symbol=symbol,
            position_qty=float(position),
            avg_cost=float(averageCost),
            market_price=float(marketPrice),
            market_value=float(marketValue),
            unrealized_pnl=float(unrealizedPNL),
            realized_pnl=float(realizedPNL),
        )

    def accountDownloadEnd(self, accountName: str) -> None:  # noqa: N802
        self.account_download_end.set()

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        self.errors.append(f"request={reqId}, details={args}")

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS positions thread stopped during disconnect: {exc}")
                return
            raise


def read_positions(settings: Settings, *, client_id: int = 67001, timeout: float | None = None) -> dict[str, Any]:
    client = ReadOnlyPositionsClient()
    host = settings.tws_host
    port = settings.tws_port
    wait_timeout = timeout if timeout is not None else settings.tws_status_timeout
    try:
        client.connect(host, port, clientId=client_id)
        threading.Thread(target=client.run_loop, daemon=True).start()
        if not client.ready.wait(wait_timeout):
            return {"status": "error", "error": "TWS positions handshake timed out", "positions": [], "errors": client.errors}
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline and not client.accounts:
            time.sleep(0.05)
        account = client.accounts[0] if client.accounts else ""
        if account:
            client.account = account
            client.reqAccountUpdates(True, account)
            client.account_download_end.wait(wait_timeout)
        return {
            "status": "ok",
            "account": account,
            "positions": [record.__dict__ for record in client.positions.values()],
            "errors": client.errors,
        }
    finally:
        try:
            if client.account:
                client.reqAccountUpdates(False, client.account)
        except Exception:
            pass
        if client.isConnected():
            client.disconnect()


def build_position_guard_report(
    *,
    settings: Settings | None = None,
    orders_snapshot: Mapping[str, Any] | None = None,
    positions_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.load()
    if orders_snapshot is None:
        from scripts.list_tws_orders import read_tws_orders

        orders_snapshot = read_tws_orders(
            host=settings.tws_host,
            port=settings.tws_port,
            client_id=settings.tws_client_id + 900,
            timeout=settings.tws_status_timeout,
        )
    if positions_snapshot is None:
        positions_snapshot = read_positions(settings, client_id=settings.tws_client_id + 901)

    positions = {
        str(row.get("symbol", "")).upper(): row
        for row in positions_snapshot.get("positions", [])
        if row.get("symbol")
    }
    open_orders = list(orders_snapshot.get("open_orders", []))
    symbols = sorted(set(positions) | {str(order.get("symbol", "")).upper() for order in open_orders if order.get("symbol")})
    quotes = _read_quotes(settings, symbols)

    rows = []
    for symbol in symbols:
        position = positions.get(symbol, {})
        symbol_orders = [order for order in open_orders if str(order.get("symbol", "")).upper() == symbol]
        open_buy_orders = [order for order in symbol_orders if order.get("action") == "BUY"]
        open_sell_orders = [order for order in symbol_orders if order.get("action") == "SELL"]
        protective_stops = [order for order in open_sell_orders if str(order.get("order_type", "")).upper().startswith("STP")]
        stop_qty = sum(float(order.get("total_quantity") or 0) for order in protective_stops)
        position_qty = float(position.get("position_qty") or 0.0)
        quote_item = quotes.get(symbol)
        quote = quote_item.get("quote") if isinstance(quote_item, Mapping) else quote_item
        quote_meta = quote_item.get("metadata", {}) if isinstance(quote_item, Mapping) else {}
        stale_quote = quote is None or quote.age_ms() > 10_000
        spread_warning = bool(quote and quote.spread is not None and quote.last > 0 and quote.spread / quote.last > 0.003)
        protection = evaluate_protection_status(
            position_qty=position_qty,
            protective_stop_qty=stop_qty,
            protective_stop_orders=protective_stops,
        )
        rows.append(
            {
                "symbol": symbol,
                "position_qty": position_qty,
                "avg_cost": position.get("avg_cost"),
                "market_price": None if quote is None else quote.last,
                "bid": None if quote is None else quote.bid,
                "ask": None if quote is None else quote.ask,
                "last": None if quote is None else quote.last,
                "quote_age_ms": None if quote is None else quote.age_ms(),
                "quote_source": quote_meta.get("quote_source") or (None if quote is None else quote.source),
                "quote_session": quote_meta.get("quote_session"),
                "market_data_type": quote_meta.get("market_data_type"),
                "market_data_type_name": quote_meta.get("market_data_type_name"),
                "snapshot_request_used": bool(quote_meta.get("snapshot_request_used", False)),
                "regulatory_snapshot_used": bool(quote_meta.get("regulatory_snapshot_used", False)),
                "paid_snapshot_risk": bool(quote_meta.get("paid_snapshot_risk", False)),
                "market_value": position.get("market_value"),
                "unrealized_pnl": position.get("unrealized_pnl"),
                "realized_pnl": position.get("realized_pnl"),
                "open_buy_orders": len(open_buy_orders),
                "open_sell_orders": len(open_sell_orders),
                "protective_stop_orders": len(protective_stops),
                "protective_stop_order_details": _order_details(protective_stops),
                "protective_stop_qty": stop_qty,
                "position_covered_by_stop": protection.position_covered_by_stop,
                "duplicate_stop_warning": protection.duplicate_stop_warning,
                "missing_stop_warning": protection.missing_stop_warning,
                "overprotected_warning": protection.overprotected_warning,
                "underprotected_warning": protection.underprotected_warning,
                "stale_quote_warning": stale_quote,
                "spread_warning": spread_warning,
                "risk_action_needed": protection.risk_action_needed or stale_quote or spread_warning,
                "recommended_action": _recommended_action(protection, stale_quote, spread_warning),
                "action_taken": "report_only",
            }
        )

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "position_guard",
        "account": positions_snapshot.get("account"),
        "status": "ok" if positions_snapshot.get("status") == "ok" and orders_snapshot.get("status") == "ok" else "warning",
        "positions_status": positions_snapshot.get("status"),
        "orders_status": orders_snapshot.get("status"),
        "position_count": len(positions),
        "open_order_count": len(open_orders),
        "open_orders": open_orders,
        "symbols": rows,
        "errors": list(positions_snapshot.get("errors", [])) + list(orders_snapshot.get("errors", [])),
    }
    write_report(report)
    return report


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def evaluate_protection_status(
    *,
    position_qty: float,
    protective_stop_qty: float,
    protective_stop_orders: Sequence[Mapping[str, Any]],
) -> ProtectionStatus:
    duplicate = len(protective_stop_orders) > 1
    if position_qty <= 0:
        overprotected = protective_stop_qty > 0
        return ProtectionStatus(
            position_covered_by_stop=protective_stop_qty == 0,
            duplicate_stop_warning=duplicate,
            missing_stop_warning=False,
            overprotected_warning=overprotected,
            underprotected_warning=False,
            risk_action_needed=duplicate or overprotected,
            recommended_action="review_duplicate_or_excess_stop" if duplicate or overprotected else "none",
        )
    missing = protective_stop_qty == 0
    under = 0 < protective_stop_qty < position_qty
    over = protective_stop_qty > position_qty
    covered = protective_stop_qty == position_qty
    if missing:
        action = "create_protective_sell_stop"
    elif under:
        action = "create_additional_protective_sell_stop_for_uncovered_qty"
    elif over:
        action = "review_duplicate_or_excess_stop"
    elif duplicate:
        action = "review_duplicate_stops"
    else:
        action = "none"
    return ProtectionStatus(
        position_covered_by_stop=covered,
        duplicate_stop_warning=duplicate,
        missing_stop_warning=missing,
        overprotected_warning=over,
        underprotected_warning=under,
        risk_action_needed=missing or under or over or duplicate,
        recommended_action=action,
    )


def _read_quotes(settings: Settings, symbols: Sequence[str]) -> dict[str, Any]:
    if not symbols:
        return {}
    cached = _read_streaming_quote_cache(symbols)
    if cached:
        return cached
    if _env_bool("NO_PAID_MARKET_DATA_REQUESTS", True) and not _env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False):
        return {}
    source = ParallelIbkrReadOnlyQuoteSource(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 902,
        timeout=settings.tws_status_timeout,
        snapshot=_env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False),
        market_data_type=1,
        workers=3,
        symbols_per_worker=4,
    )
    return {
        quote.symbol.upper(): {
            "quote": quote,
            "metadata": {
                "quote_source": quote.source,
                "market_data_type": 1,
                "market_data_type_name": "live",
                "snapshot_request_used": _env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False),
                "regulatory_snapshot_used": False,
                "paid_snapshot_risk": False,
            },
        }
        for quote in source.get_quotes(symbols)
    }


def _read_streaming_quote_cache(symbols: Sequence[str]) -> dict[str, Any]:
    latest = PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json"
    if not latest.exists():
        return {}
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    streaming = payload.get("streaming_quotes")
    if not isinstance(streaming, Mapping):
        return {}
    wanted = {symbol.upper() for symbol in symbols}
    quotes: dict[str, Any] = {}
    for symbol, row in streaming.items():
        symbol = str(symbol).upper()
        if symbol not in wanted or not isinstance(row, Mapping):
            continue
        timestamp = _parse_timestamp(row.get("timestamp"))
        last = _float(row.get("last"))
        bid = _float(row.get("bid"))
        ask = _float(row.get("ask"))
        if last is None and bid is not None and ask is not None:
            last = (bid + ask) / 2
        if last is None:
            continue
        market_data_type = _market_data_type_from_name(row.get("market_data_type"))
        quotes[symbol] = {
            "quote": Quote(
                symbol=symbol,
                last=last,
                bid=bid,
                ask=ask,
                close=_float(row.get("close")),
                volume=None if row.get("volume") is None else int(row.get("volume")),
                timestamp=timestamp,
                source=str(row.get("source") or "ibkr_streaming"),
            ),
            "metadata": {
                "quote_source": str(row.get("source") or "ibkr_streaming"),
                "quote_session": "streaming_cache",
                "market_data_type": market_data_type,
                "market_data_type_name": row.get("market_data_type") or "unknown",
                "snapshot_request_used": False,
                "regulatory_snapshot_used": False,
                "paid_snapshot_risk": False,
            },
        }
    return quotes


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _float(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _market_data_type_from_name(value: object) -> int | None:
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower()
    return {"live": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4, "delayed frozen": 4}.get(text)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _recommended_action(
    protection: ProtectionStatus,
    stale_quote: bool,
    spread_warning: bool,
) -> str:
    if protection.recommended_action != "none":
        return protection.recommended_action
    if stale_quote:
        return "review_stale_position_quote"
    if spread_warning:
        return "review_wide_position_spread"
    return "none"


def _order_details(orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_id": order.get("order_id"),
            "action": order.get("action"),
            "order_type": order.get("order_type"),
            "total_quantity": order.get("total_quantity"),
            "aux_price": order.get("aux_price"),
            "limit_price": order.get("limit_price"),
            "status": order.get("status"),
            "order_ref": order.get("order_ref"),
        }
        for order in orders
    ]
