import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Set, Tuple

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from trading.models import TradeProposal
from trading.price_normalizer import normalize_order_price


SUBMITTED_ORDER_STATUSES = {
    "ApiPending",
    "PendingSubmit",
    "PreSubmitted",
    "Submitted",
    "Filled",
}

def normalize_us_stock_price(price: float) -> float:
    return float(Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class OrderConfirmation:
    order_ids: Tuple[int, ...]
    acknowledged_order_ids: Optional[Tuple[int, ...]] = None
    statuses: Dict[int, str] = field(default_factory=dict)
    open_order_states: Dict[int, str] = field(default_factory=dict)
    messages: Tuple[str, ...] = field(default_factory=tuple)
    timings: Dict[str, float] = field(default_factory=dict)
    raw_limit_price: Optional[float] = None
    normalized_limit_price: Optional[float] = None
    raw_stop_price: Optional[float] = None
    normalized_stop_price: Optional[float] = None
    parent_transmit: Optional[bool] = None
    child_transmit: Optional[bool] = None
    child_rejected_parent_cancel_requested: bool = False

    @property
    def acknowledged_ids(self) -> Tuple[int, ...]:
        if self.acknowledged_order_ids is None:
            return self.order_ids
        return self.acknowledged_order_ids

    @property
    def pending_confirmation(self) -> bool:
        return set(self.acknowledged_ids) != set(self.order_ids)

    def details(self) -> str:
        status_text = ", ".join(
            f"{order_id}:{status}" for order_id, status in sorted(self.statuses.items())
        )
        state_text = ", ".join(
            f"{order_id}:{state}"
            for order_id, state in sorted(self.open_order_states.items())
        )
        parts = [f"order_ids={list(self.order_ids)}"]
        if self.acknowledged_order_ids is not None:
            parts.append(f"acknowledged_order_ids={list(self.acknowledged_order_ids)}")
        if self.pending_confirmation:
            parts.append("pending_confirmation=true")
        if status_text:
            parts.append(f"statuses={{{status_text}}}")
        if state_text:
            parts.append(f"open_order_states={{{state_text}}}")
        if self.messages:
            parts.append("messages=" + " | ".join(self.messages))
        if self.parent_transmit is not None:
            parts.append(f"parent_transmit={str(self.parent_transmit).lower()}")
        if self.child_transmit is not None:
            parts.append(f"child_transmit={str(self.child_transmit).lower()}")
        if self.raw_limit_price is not None:
            parts.append(f"raw_limit_price={self.raw_limit_price}")
        if self.normalized_limit_price is not None:
            parts.append(f"normalized_limit_price={self.normalized_limit_price}")
        if self.raw_stop_price is not None:
            parts.append(f"raw_stop_price={self.raw_stop_price}")
        if self.normalized_stop_price is not None:
            parts.append(f"normalized_stop_price={self.normalized_stop_price}")
        parts.append(
            "child_rejected_parent_cancel_requested="
            + str(self.child_rejected_parent_cancel_requested).lower()
        )
        return ", ".join(parts)


@dataclass(frozen=True)
class TwsConnectionStatus:
    connected: bool
    ready_for_orders: bool
    account_count: int = 0
    accounts: Tuple[str, ...] = ()
    paper_account: Optional[str] = None
    next_order_id_received: bool = False
    error: str = ""
    timings: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "connected": self.connected,
            "ready_for_orders": self.ready_for_orders,
            "account_count": self.account_count,
            "accounts": list(self.accounts),
            "paper_account": self.paper_account,
            "next_order_id_received": self.next_order_id_received,
            "error": self.error,
            "timings": dict(self.timings),
        }


class TwsPaperClient(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.accounts_ready = threading.Event()
        self.next_order_id: Optional[int] = None
        self.accounts: List[str] = []
        self.errors: List[str] = []
        self.expected_order_ids: Set[int] = set()
        self.acknowledged_order_ids: Set[int] = set()
        self.order_statuses: Dict[int, str] = {}
        self.open_order_states: Dict[int, str] = {}
        self.allow_open_order_confirmation = False
        self.orders_acknowledged = threading.Event()
        self.open_orders_received = threading.Event()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.ready.set()

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS client thread stopped during disconnect: {exc}")
                return
            raise

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item for item in accountsList.split(",") if item]
        self.accounts_ready.set()

    def error(self, reqId: int, *args: object) -> None:
        self.errors.append(f"request={reqId}, details={args}")
        if reqId in self.expected_order_ids:
            self.orders_acknowledged.set()

    def openOrder(self, orderId: int, contract: object, order: object, orderState: object) -> None:  # noqa: N802,E501
        if orderId in self.expected_order_ids:
            status = getattr(orderState, "status", "")
            if status:
                self.open_order_states[orderId] = str(status)
            if self.allow_open_order_confirmation:
                self.acknowledged_order_ids.add(orderId)
        if self.acknowledged_order_ids == self.expected_order_ids:
            self.orders_acknowledged.set()

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_orders_received.set()

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
        if orderId not in self.expected_order_ids:
            return
        self.order_statuses[orderId] = status
        if status in SUBMITTED_ORDER_STATUSES:
            self.acknowledged_order_ids.add(orderId)
        self.orders_acknowledged.set()


class TwsPaperBroker:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id

    def check_status(self, timeout: float = 2.0) -> TwsConnectionStatus:
        started = time.perf_counter()
        client = TwsPaperClient()
        try:
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            deadline = time.perf_counter() + timeout
            ready = client.ready.wait(timeout)
            accounts_ready = client.accounts_ready.wait(max(0.0, deadline - time.perf_counter()))
            accounts = tuple(client.accounts)
            paper_account = accounts[0] if len(accounts) == 1 and accounts[0].startswith("DU") else None
            next_order_id_received = client.next_order_id is not None
            connected = client.isConnected() and ready and accounts_ready
            ready_for_orders = connected and paper_account is not None and next_order_id_received
            error = ""
            if not connected:
                error = "TWS API is not reachable or not fully logged in"
            elif paper_account is None:
                error = "Expected exactly one DU paper account"
            elif not next_order_id_received:
                error = "TWS did not provide nextValidId"
            return TwsConnectionStatus(
                connected=connected,
                ready_for_orders=ready_for_orders,
                account_count=len(accounts),
                accounts=accounts,
                paper_account=paper_account,
                next_order_id_received=next_order_id_received,
                error=error,
                timings={"tws_status_check_ms": self._elapsed_ms(started)},
            )
        except Exception as exc:
            return TwsConnectionStatus(
                connected=False,
                ready_for_orders=False,
                error=str(exc),
                timings={"tws_status_check_ms": self._elapsed_ms(started)},
            )
        finally:
            if client.isConnected():
                client.disconnect()

    def submit_bracket(
        self,
        proposal: TradeProposal,
        transmit: bool,
        outside_rth: bool = False,
        timeout: float = 10.0,
    ) -> OrderConfirmation:
        total_started = time.perf_counter()
        timings: Dict[str, float] = {}
        client = TwsPaperClient()
        parent_placed = False
        child_rejected_parent_cancel_requested = False
        try:
            connect_started = time.perf_counter()
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            if not client.ready.wait(timeout) or not client.accounts_ready.wait(timeout):
                raise RuntimeError("TWS paper connection timed out")
            timings["broker_connect_handshake_ms"] = self._elapsed_ms(connect_started)

            if len(client.accounts) != 1 or not client.accounts[0].startswith("DU"):
                raise RuntimeError("Orders are restricted to one DU paper account")
            if client.next_order_id is None:
                raise RuntimeError("TWS did not provide a valid order ID")

            parent_id = client.next_order_id
            stop_id = parent_id + 1
            account = client.accounts[0]
            contract = self._stock_contract(proposal.symbol)
            parent, stop = self._bracket_orders(
                proposal,
                account,
                parent_id,
                stop_id,
                transmit,
                outside_rth,
            )
            client.expected_order_ids = {parent_id, stop_id}
            client.allow_open_order_confirmation = True
            place_started = time.perf_counter()
            client.placeOrder(parent_id, contract, parent)
            parent_placed = True
            try:
                client.placeOrder(stop_id, contract, stop)
            except Exception as exc:
                child_rejected_parent_cancel_requested = self._cancel_parent_order(
                    client,
                    parent_id,
                    parent_placed,
                )
                raise RuntimeError(
                    "TWS child stop order placement failed; "
                    f"parent_order_id={parent_id}, child_order_id={stop_id}, "
                    "parent_transmit=false, "
                    f"child_transmit={str(transmit).lower()}, "
                    f"raw_limit_price={proposal.limit_price}, "
                    f"normalized_limit_price={parent.lmtPrice}, "
                    f"raw_stop_price={proposal.stop_price}, "
                    f"normalized_stop_price={stop.auxPrice}, "
                    "child_rejected_parent_cancel_requested="
                    + str(child_rejected_parent_cancel_requested).lower()
                ) from exc
            timings["broker_place_orders_ms"] = self._elapsed_ms(place_started)

            ack_started = time.perf_counter()
            if not client.orders_acknowledged.wait(timeout):
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
                fallback_started = time.perf_counter()
                client.reqOpenOrders()
                client.open_orders_received.wait(5.0)
                timings["broker_open_orders_fallback_ms"] = self._elapsed_ms(
                    fallback_started
                )
            else:
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
            order_errors = self._fatal_order_errors(client, {parent_id, stop_id})
            if order_errors:
                if self._fatal_order_errors(client, {stop_id}):
                    child_rejected_parent_cancel_requested = self._cancel_parent_order(
                        client,
                        parent_id,
                        parent_placed,
                    )
                raise RuntimeError(
                    "TWS rejected an order: "
                    + "; ".join(order_errors)
                    + f"; parent_order_id={parent_id}; child_order_id={stop_id}; "
                    + "parent_transmit=false; "
                    + f"child_transmit={str(transmit).lower()}; "
                    + f"raw_limit_price={proposal.limit_price}; "
                    + f"normalized_limit_price={parent.lmtPrice}; "
                    + f"raw_stop_price={proposal.stop_price}; "
                    + f"normalized_stop_price={stop.auxPrice}; "
                    + "child_rejected_parent_cancel_requested="
                    + str(child_rejected_parent_cancel_requested).lower()
                )
            timings["broker_total_ms"] = self._elapsed_ms(total_started)
            return self._confirmation(
                client,
                (parent_id, stop_id),
                timings,
                raw_limit_price=proposal.limit_price,
                normalized_limit_price=parent.lmtPrice,
                raw_stop_price=proposal.stop_price,
                normalized_stop_price=stop.auxPrice,
                parent_transmit=False,
                child_transmit=transmit,
                child_rejected_parent_cancel_requested=child_rejected_parent_cancel_requested,
            )
        finally:
            if client.isConnected():
                client.disconnect()

    def submit_limit(
        self,
        proposal: TradeProposal,
        transmit: bool,
        outside_rth: bool = False,
        timeout: float = 10.0,
    ) -> OrderConfirmation:
        total_started = time.perf_counter()
        timings: Dict[str, float] = {}
        client = TwsPaperClient()
        try:
            connect_started = time.perf_counter()
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            if not client.ready.wait(timeout) or not client.accounts_ready.wait(timeout):
                raise RuntimeError("TWS paper connection timed out")
            timings["broker_connect_handshake_ms"] = self._elapsed_ms(connect_started)

            if len(client.accounts) != 1 or not client.accounts[0].startswith("DU"):
                raise RuntimeError("Orders are restricted to one DU paper account")
            if client.next_order_id is None:
                raise RuntimeError("TWS did not provide a valid order ID")

            order_id = client.next_order_id
            contract = self._stock_contract(proposal.symbol)
            order = self._limit_order(
                proposal,
                client.accounts[0],
                order_id,
                transmit,
                outside_rth,
            )
            client.expected_order_ids = {order_id}
            client.allow_open_order_confirmation = True
            place_started = time.perf_counter()
            client.placeOrder(order_id, contract, order)
            timings["broker_place_orders_ms"] = self._elapsed_ms(place_started)

            ack_started = time.perf_counter()
            if not client.orders_acknowledged.wait(timeout):
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
                fallback_started = time.perf_counter()
                client.reqOpenOrders()
                client.open_orders_received.wait(5.0)
                timings["broker_open_orders_fallback_ms"] = self._elapsed_ms(
                    fallback_started
                )
            else:
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
            order_errors = self._fatal_order_errors(client, {order_id})
            if order_errors:
                raise RuntimeError("TWS rejected an order: " + "; ".join(order_errors))
            timings["broker_total_ms"] = self._elapsed_ms(total_started)
            return self._confirmation(
                client,
                (order_id,),
                timings,
                raw_limit_price=proposal.limit_price,
                normalized_limit_price=order.lmtPrice,
            )
        finally:
            if client.isConnected():
                client.disconnect()

    def submit_stop(
        self,
        *,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
        order_ref: str,
        transmit: bool,
        outside_rth: bool = False,
        timeout: float = 10.0,
    ) -> OrderConfirmation:
        if action != "SELL":
            raise ValueError("protective stop submission only supports SELL")
        total_started = time.perf_counter()
        timings: Dict[str, float] = {}
        client = TwsPaperClient()
        try:
            connect_started = time.perf_counter()
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            if not client.ready.wait(timeout) or not client.accounts_ready.wait(timeout):
                raise RuntimeError("TWS paper connection timed out")
            timings["broker_connect_handshake_ms"] = self._elapsed_ms(connect_started)

            if len(client.accounts) != 1 or not client.accounts[0].startswith("DU"):
                raise RuntimeError("Orders are restricted to one DU paper account")
            if client.next_order_id is None:
                raise RuntimeError("TWS did not provide a valid order ID")

            order_id = client.next_order_id
            contract = self._stock_contract(symbol)
            order = self._stop_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                stop_price=stop_price,
                account=client.accounts[0],
                order_id=order_id,
                order_ref=order_ref,
                transmit=transmit,
                outside_rth=outside_rth,
            )
            client.expected_order_ids = {order_id}
            client.allow_open_order_confirmation = True
            place_started = time.perf_counter()
            client.placeOrder(order_id, contract, order)
            timings["broker_place_orders_ms"] = self._elapsed_ms(place_started)

            ack_started = time.perf_counter()
            if not client.orders_acknowledged.wait(timeout):
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
                fallback_started = time.perf_counter()
                client.reqOpenOrders()
                client.open_orders_received.wait(5.0)
                timings["broker_open_orders_fallback_ms"] = self._elapsed_ms(fallback_started)
            else:
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
            order_errors = self._fatal_order_errors(client, {order_id})
            if order_errors:
                raise RuntimeError("TWS rejected an order: " + "; ".join(order_errors))
            timings["broker_total_ms"] = self._elapsed_ms(total_started)
            return self._confirmation(
                client,
                (order_id,),
                timings,
                raw_stop_price=stop_price,
                normalized_stop_price=order.auxPrice,
                child_transmit=transmit,
            )
        finally:
            if client.isConnected():
                client.disconnect()

    def submit_stop_limit(
        self,
        *,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
        limit_price: float,
        order_ref: str,
        transmit: bool,
        outside_rth: bool = False,
        timeout: float = 10.0,
    ) -> OrderConfirmation:
        if action != "SELL":
            raise ValueError("protective stop-limit submission only supports SELL")
        total_started = time.perf_counter()
        timings: Dict[str, float] = {}
        client = TwsPaperClient()
        try:
            connect_started = time.perf_counter()
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            if not client.ready.wait(timeout) or not client.accounts_ready.wait(timeout):
                raise RuntimeError("TWS paper connection timed out")
            timings["broker_connect_handshake_ms"] = self._elapsed_ms(connect_started)

            if len(client.accounts) != 1 or not client.accounts[0].startswith("DU"):
                raise RuntimeError("Orders are restricted to one DU paper account")
            if client.next_order_id is None:
                raise RuntimeError("TWS did not provide a valid order ID")

            order_id = client.next_order_id
            contract = self._stock_contract(symbol)
            order = self._stop_limit_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                stop_price=stop_price,
                limit_price=limit_price,
                account=client.accounts[0],
                order_id=order_id,
                order_ref=order_ref,
                transmit=transmit,
                outside_rth=outside_rth,
            )
            client.expected_order_ids = {order_id}
            client.allow_open_order_confirmation = True
            place_started = time.perf_counter()
            client.placeOrder(order_id, contract, order)
            timings["broker_place_orders_ms"] = self._elapsed_ms(place_started)

            ack_started = time.perf_counter()
            if not client.orders_acknowledged.wait(timeout):
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
                fallback_started = time.perf_counter()
                client.reqOpenOrders()
                client.open_orders_received.wait(5.0)
                timings["broker_open_orders_fallback_ms"] = self._elapsed_ms(fallback_started)
            else:
                timings["broker_wait_ack_ms"] = self._elapsed_ms(ack_started)
            order_errors = self._fatal_order_errors(client, {order_id})
            if order_errors:
                raise RuntimeError("TWS rejected an order: " + "; ".join(order_errors))
            timings["broker_total_ms"] = self._elapsed_ms(total_started)
            return self._confirmation(
                client,
                (order_id,),
                timings,
                raw_limit_price=limit_price,
                normalized_limit_price=order.lmtPrice,
                raw_stop_price=stop_price,
                normalized_stop_price=order.auxPrice,
                child_transmit=transmit,
            )
        finally:
            if client.isConnected():
                client.disconnect()

    @staticmethod
    def _cancel_parent_order(
        client: TwsPaperClient,
        parent_id: int,
        parent_placed: bool,
    ) -> bool:
        if not parent_placed:
            return False
        try:
            client.cancelOrder(parent_id, "")
        except TypeError:
            client.cancelOrder(parent_id)
        return True

    @classmethod
    def _fatal_order_errors(
        cls,
        client: TwsPaperClient,
        order_ids: Set[int],
    ) -> List[str]:
        return [
            error
            for error in cls._order_errors(client, order_ids)
            if cls._is_fatal_order_error(error)
        ]

    @staticmethod
    def _order_errors(client: TwsPaperClient, order_ids: Set[int]) -> List[str]:
        return [
            error
            for error in client.errors
            if any(f"request={order_id}," in error for order_id in order_ids)
        ]

    @staticmethod
    def _is_fatal_order_error(error: str) -> bool:
        return (
            ", 399," not in error
            and "(399," not in error
            and "Order Event Warning" not in error
        )

    @staticmethod
    def _confirmation(
        client: TwsPaperClient,
        order_ids: Tuple[int, ...],
        timings: Optional[Dict[str, float]] = None,
        *,
        raw_limit_price: Optional[float] = None,
        normalized_limit_price: Optional[float] = None,
        raw_stop_price: Optional[float] = None,
        normalized_stop_price: Optional[float] = None,
        parent_transmit: Optional[bool] = None,
        child_transmit: Optional[bool] = None,
        child_rejected_parent_cancel_requested: bool = False,
    ) -> OrderConfirmation:
        return OrderConfirmation(
            order_ids=order_ids,
            acknowledged_order_ids=tuple(sorted(client.acknowledged_order_ids)),
            statuses=dict(client.order_statuses),
            open_order_states=dict(client.open_order_states),
            messages=tuple(client.errors),
            timings={} if timings is None else dict(timings),
            raw_limit_price=raw_limit_price,
            normalized_limit_price=normalized_limit_price,
            raw_stop_price=raw_stop_price,
            normalized_stop_price=normalized_stop_price,
            parent_transmit=parent_transmit,
            child_transmit=child_transmit,
            child_rejected_parent_cancel_requested=child_rejected_parent_cancel_requested,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @staticmethod
    def _stock_contract(symbol: str) -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        return contract

    @staticmethod
    def _bracket_orders(
        proposal: TradeProposal,
        account: str,
        parent_id: int,
        stop_id: int,
        transmit: bool,
        outside_rth: bool = False,
    ) -> Tuple[Order, Order]:
        closing_side = "SELL" if proposal.side == "BUY" else "BUY"

        parent = Order()
        parent.orderId = parent_id
        parent.account = account
        parent.action = proposal.side
        parent.orderType = "LMT"
        parent.totalQuantity = Decimal(proposal.quantity)
        parent.lmtPrice = normalize_order_price(
            symbol=proposal.symbol,
            side=proposal.side,
            order_type="LMT",
            price=proposal.limit_price,
        )
        parent.tif = "DAY"
        parent.outsideRth = outside_rth
        parent.orderRef = proposal.idempotency_key
        parent.transmit = False

        stop = Order()
        stop.orderId = stop_id
        stop.account = account
        stop.action = closing_side
        stop.orderType = "STP"
        stop.totalQuantity = Decimal(proposal.quantity)
        stop.auxPrice = normalize_order_price(
            symbol=proposal.symbol,
            side=closing_side,
            order_type="STP",
            price=proposal.stop_price,
        )
        stop.parentId = parent_id
        stop.tif = "GTC"
        stop.outsideRth = outside_rth
        stop.orderRef = proposal.idempotency_key
        stop.transmit = transmit
        return parent, stop

    @staticmethod
    def _limit_order(
        proposal: TradeProposal,
        account: str,
        order_id: int,
        transmit: bool,
        outside_rth: bool = False,
    ) -> Order:
        order = Order()
        order.orderId = order_id
        order.account = account
        order.action = proposal.side
        order.orderType = "LMT"
        order.totalQuantity = Decimal(proposal.quantity)
        order.lmtPrice = normalize_order_price(
            symbol=proposal.symbol,
            side=proposal.side,
            order_type="LMT",
            price=proposal.limit_price,
        )
        order.tif = "DAY"
        order.outsideRth = outside_rth
        order.orderRef = proposal.idempotency_key
        order.transmit = transmit
        return order

    @staticmethod
    def _stop_order(
        *,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
        account: str,
        order_id: int,
        order_ref: str,
        transmit: bool,
        outside_rth: bool = False,
    ) -> Order:
        order = Order()
        order.orderId = order_id
        order.account = account
        order.action = action
        order.orderType = "STP"
        order.totalQuantity = Decimal(quantity)
        order.auxPrice = normalize_order_price(
            symbol=symbol,
            side="SELL",
            order_type="STP",
            price=stop_price,
        )
        order.tif = "GTC"
        order.outsideRth = outside_rth
        order.orderRef = order_ref
        order.transmit = transmit
        return order

    @staticmethod
    def _stop_limit_order(
        *,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
        limit_price: float,
        account: str,
        order_id: int,
        order_ref: str,
        transmit: bool,
        outside_rth: bool = False,
    ) -> Order:
        order = Order()
        order.orderId = order_id
        order.account = account
        order.action = action
        order.orderType = "STP LMT"
        order.totalQuantity = Decimal(quantity)
        order.auxPrice = normalize_order_price(
            symbol=symbol,
            side="SELL",
            order_type="STP",
            price=stop_price,
        )
        order.lmtPrice = normalize_order_price(
            symbol=symbol,
            side="SELL",
            order_type="LMT",
            price=limit_price,
        )
        order.tif = "GTC"
        order.outsideRth = outside_rth
        order.orderRef = order_ref
        order.transmit = transmit
        return order
