from decimal import Decimal
import unittest
from threading import Event
from unittest.mock import patch

from trading.models import TradeProposal
from trading.tws_paper import (
    OrderConfirmation,
    TwsPaperBroker,
    TwsPaperClient,
    normalize_us_stock_price,
)


class TwsPaperBrokerTests(unittest.TestCase):
    def test_us_stock_price_normalizes_to_cent_tick(self) -> None:
        self.assertEqual(normalize_us_stock_price(311.5189), 311.52)

    def test_transmitted_order_requires_order_status_ack(self) -> None:
        client = TwsPaperClient()
        client.expected_order_ids = {100}

        client.openOrder(100, object(), object(), object())

        self.assertEqual(client.acknowledged_order_ids, set())
        self.assertFalse(client.orders_acknowledged.is_set())

        client.orderStatus(
            100,
            "Submitted",
            Decimal("0"),
            Decimal("1"),
            0.0,
            0,
            0,
            0.0,
            0,
            "",
            0.0,
        )

        self.assertEqual(client.acknowledged_order_ids, {100})
        self.assertTrue(client.orders_acknowledged.is_set())

    def test_staged_order_can_ack_from_open_order(self) -> None:
        client = TwsPaperClient()
        client.expected_order_ids = {100}
        client.allow_open_order_confirmation = True

        client.openOrder(100, object(), object(), object())

        self.assertEqual(client.acknowledged_order_ids, {100})
        self.assertTrue(client.orders_acknowledged.is_set())

    def test_bracket_has_protective_stop_and_no_transmission_by_default(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0001",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=False,
        )

        self.assertEqual(parent.action, "BUY")
        self.assertEqual(parent.orderType, "LMT")
        self.assertFalse(parent.transmit)
        self.assertEqual(stop.action, "SELL")
        self.assertEqual(stop.orderType, "STP")
        self.assertEqual(stop.parentId, 100)
        self.assertFalse(stop.transmit)
        self.assertFalse(parent.outsideRth)
        self.assertFalse(stop.outsideRth)
        self.assertEqual(parent.lmtPrice, 190.0)
        self.assertEqual(stop.auxPrice, 185.0)

    def test_transmitted_bracket_only_transmits_on_final_stop_child(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0002",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=True,
        )

        self.assertFalse(parent.transmit)
        self.assertTrue(stop.transmit)

    def test_bracket_child_failure_requests_parent_cancel(self) -> None:
        class FakeClient:
            last_instance = None

            def __init__(self) -> None:
                FakeClient.last_instance = self
                self.ready = Event()
                self.ready.set()
                self.accounts_ready = Event()
                self.accounts_ready.set()
                self.accounts = ["DU12345"]
                self.next_order_id = 100
                self.expected_order_ids = set()
                self.allow_open_order_confirmation = False
                self.orders_acknowledged = Event()
                self.open_orders_received = Event()
                self.acknowledged_order_ids = set()
                self.order_statuses = {}
                self.open_order_states = {}
                self.errors = []
                self.placed = []
                self.cancelled = []

            def connect(self, host: str, port: int, clientId: int) -> None:  # noqa: N803
                return

            def run_loop(self) -> None:
                return

            def placeOrder(self, order_id: int, contract: object, order: object) -> None:  # noqa: N802
                self.placed.append(order_id)
                if order_id == 101:
                    raise RuntimeError("child rejected")

            def cancelOrder(self, order_id: int, reason: str = "") -> None:  # noqa: N802
                self.cancelled.append((order_id, reason))

            def isConnected(self) -> bool:  # noqa: N802
                return True

            def disconnect(self) -> None:
                return

        proposal = TradeProposal("AAPL", "BUY", 1, 190.001, 185.009, "trade-0005")
        broker = TwsPaperBroker("127.0.0.1", 7497, 22)

        with patch("trading.tws_paper.TwsPaperClient", FakeClient):
            with self.assertRaisesRegex(RuntimeError, "parent_cancel_requested=true"):
                broker.submit_bracket(proposal, transmit=True)

        fake = FakeClient.last_instance
        self.assertIsNotNone(fake)
        self.assertEqual(fake.placed, [100, 101])
        self.assertEqual(fake.cancelled, [(100, "")])

    def test_outside_rth_is_configurable_for_both_bracket_legs(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0003",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=True,
            outside_rth=True,
        )

        self.assertTrue(parent.outsideRth)
        self.assertTrue(stop.outsideRth)

    def test_limit_order_can_transmit_outside_rth_without_stop_leg(self) -> None:
        proposal = TradeProposal(
            "MSFT",
            "BUY",
            1,
            300.0,
            None,
            "trade-0004",
        )

        order = TwsPaperBroker._limit_order(
            proposal,
            "DU12345",
            100,
            transmit=True,
            outside_rth=True,
        )

        self.assertEqual(order.action, "BUY")
        self.assertEqual(order.orderType, "LMT")
        self.assertEqual(order.totalQuantity, 1)
        self.assertEqual(order.lmtPrice, 300.0)
        self.assertTrue(order.transmit)
        self.assertTrue(order.outsideRth)

    def test_stop_limit_order_is_sell_gtc_outside_rth_with_order_ref(self) -> None:
        order = TwsPaperBroker._stop_limit_order(
            symbol="AAPL",
            action="SELL",
            quantity=17,
            stop_price=299.061,
            limit_price=297.571,
            account="DU12345",
            order_id=100,
            order_ref="protect-aapl-test",
            transmit=True,
            outside_rth=True,
        )

        self.assertEqual(order.action, "SELL")
        self.assertEqual(order.orderType, "STP LMT")
        self.assertEqual(order.totalQuantity, 17)
        self.assertEqual(order.auxPrice, 299.06)
        self.assertEqual(order.lmtPrice, 297.58)
        self.assertEqual(order.tif, "GTC")
        self.assertTrue(order.outsideRth)
        self.assertEqual(order.orderRef, "protect-aapl-test")
        self.assertTrue(order.transmit)

    def test_order_confirmation_records_partial_ack_as_pending(self) -> None:
        confirmation = OrderConfirmation(
            order_ids=(10, 11),
            acknowledged_order_ids=(10,),
            messages=("request=11, details=(11, 399, 'Order Event Warning', '')",),
            timings={"broker_total_ms": 12.5},
        )

        self.assertTrue(confirmation.pending_confirmation)
        self.assertEqual(confirmation.acknowledged_ids, (10,))
        self.assertEqual(confirmation.timings["broker_total_ms"], 12.5)
        details = confirmation.details()
        self.assertIn("pending_confirmation=true", details)
        self.assertIn("acknowledged_order_ids=[10]", details)

    def test_order_event_warning_is_not_fatal_order_error(self) -> None:
        client = TwsPaperClient()
        client.errors.append(
            "request=12, details=(12, 399, 'Order Event Warning: outside RTH', '')"
        )

        self.assertEqual(TwsPaperBroker._fatal_order_errors(client, {12}), [])

        client.errors.append("request=12, details=(12, 201, 'Order rejected', '')")
        fatal = TwsPaperBroker._fatal_order_errors(client, {12})
        self.assertEqual(len(fatal), 1)
        self.assertIn("Order rejected", fatal[0])


if __name__ == "__main__":
    unittest.main()
