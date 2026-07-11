from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import unittest

import trading.ibkr_streaming as streaming_module
from trading.ibkr_streaming import (
    ASK_PRICE_TICK,
    BID_PRICE_TICK,
    LAST_PRICE_TICK,
    VOLUME_SIZE_TICK,
    IbkrStreamingQuoteClient,
    IbkrStreamingQuoteSource,
)


class FakeStreamingClient:
    def __init__(self, ticker_id_to_symbol):
        self.inner = IbkrStreamingQuoteClient(ticker_id_to_symbol)
        self.ready = self.inner.ready
        self.ready.set()
        self.quote_states = self.inner.quote_states
        self.errors = self.inner.errors
        self.connected = False
        self.market_data_type = None
        self.requests = []
        self.cancelled = []

    def connect(self, host, port, clientId):  # noqa: N803
        self.connected = True

    def run_loop(self):
        return

    def reqMarketDataType(self, market_data_type):  # noqa: N802
        self.market_data_type = market_data_type

    def reqMktData(self, ticker_id, contract, generic_tick_list, snapshot, regulatory_snapshot, options):  # noqa: N802,E501
        self.requests.append((ticker_id, contract.symbol, snapshot, regulatory_snapshot))

    def cancelMktData(self, ticker_id):  # noqa: N802
        self.cancelled.append(ticker_id)

    def isConnected(self):  # noqa: N802
        return self.connected

    def disconnect(self):
        self.connected = False


class IbkrStreamingQuoteTests(unittest.TestCase):
    def test_req_mkt_data_uses_streaming_snapshot_disabled(self) -> None:
        fake = None

        def factory(mapping):
            nonlocal fake
            fake = FakeStreamingClient(mapping)
            return fake

        source = IbkrStreamingQuoteSource(
            symbols=["AAPL", "MSFT", "NVDA"],
            client_factory=factory,
        )

        self.assertTrue(source.start(timeout=0.01))

        self.assertEqual(fake.market_data_type, 1)
        self.assertEqual([item[1] for item in fake.requests], ["AAPL", "MSFT", "NVDA"])
        self.assertTrue(all(item[2] is False for item in fake.requests))
        self.assertTrue(all(item[3] is False for item in fake.requests))

    def test_more_than_max_symbols_is_truncated_safely(self) -> None:
        source = IbkrStreamingQuoteSource(
            symbols=["AAPL", "MSFT", "NVDA", "TSLA"],
            max_symbols=3,
            client_factory=FakeStreamingClient,
        )

        self.assertEqual(source.symbols, ("AAPL", "MSFT", "NVDA"))
        self.assertIn("truncated", " ".join(source.errors))

    def test_tick_price_updates_quote_cache(self) -> None:
        client = IbkrStreamingQuoteClient({30000: "AAPL"})

        client.tickPrice(30000, BID_PRICE_TICK, 100.0, object())
        client.tickPrice(30000, ASK_PRICE_TICK, 100.2, object())
        client.tickPrice(30000, LAST_PRICE_TICK, 100.1, object())
        client.tickSize(30000, VOLUME_SIZE_TICK, 123)

        quote = client.quote_states["AAPL"].to_quote()
        self.assertIsNotNone(quote)
        self.assertEqual(quote.last, 100.1)
        self.assertEqual(quote.bid, 100.0)
        self.assertEqual(quote.ask, 100.2)
        self.assertEqual(quote.volume, 123)

    def test_bid_ask_midpoint_can_create_usable_quote(self) -> None:
        client = IbkrStreamingQuoteClient({30000: "MSFT"})

        client.tickPrice(30000, BID_PRICE_TICK, 200.0, object())
        client.tickPrice(30000, ASK_PRICE_TICK, 200.2, object())

        quote = client.quote_states["MSFT"].to_quote()
        self.assertIsNotNone(quote)
        self.assertEqual(quote.last, 200.1)

    def test_stale_quote_is_detected(self) -> None:
        source = IbkrStreamingQuoteSource(
            symbols=["AAPL"],
            stale_ms=3000,
            client_factory=FakeStreamingClient,
        )
        state = source._client.quote_states["AAPL"]
        state.bid = 100.0
        state.ask = 100.2
        state.timestamp = datetime.now(timezone.utc) - timedelta(seconds=4)

        self.assertTrue(source.is_stale("AAPL"))

    def test_shutdown_cancels_subscriptions(self) -> None:
        source = IbkrStreamingQuoteSource(
            symbols=["AAPL", "MSFT"],
            client_factory=FakeStreamingClient,
        )
        source.start(timeout=0.01)
        source.stop()

        self.assertEqual(source._client.cancelled, [30000, 30001])
        self.assertFalse(source._client.connected)

    def test_streaming_errors_are_recorded_per_symbol(self) -> None:
        client = IbkrStreamingQuoteClient({30000: "AAPL"})

        client.error(30000, 101, "No market data permissions")

        self.assertTrue(client.errors)
        self.assertTrue(client.quote_states["AAPL"].errors)

    def test_streaming_module_does_not_call_order_apis(self) -> None:
        source = Path(streaming_module.__file__).read_text(encoding="utf-8")
        forbidden = ("placeOrder(", "cancelOrder(", "reqPositions(", "reqAccountSummary(")

        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
