import unittest

from trading.ibkr_readonly import (
    ASK_PRICE_TICK,
    BID_PRICE_TICK,
    CLOSE_PRICE_TICK,
    DELAYED_ASK_PRICE_TICK,
    DELAYED_BID_PRICE_TICK,
    DELAYED_LAST_PRICE_TICK,
    IbkrReadOnlyQuoteClient,
    IbkrReadOnlyQuoteSource,
    LAST_PRICE_TICK,
    VOLUME_SIZE_TICK,
)
from trading.simulation import StrategySimulationConfig, quote_source


class IbkrReadOnlyQuoteClientTests(unittest.TestCase):
    def test_tick_callbacks_build_normalized_quote(self) -> None:
        client = IbkrReadOnlyQuoteClient({10000: "AAPL"})

        client.tickPrice(10000, BID_PRICE_TICK, 100.0, object())
        client.tickPrice(10000, ASK_PRICE_TICK, 100.1, object())
        client.tickPrice(10000, LAST_PRICE_TICK, 100.05, object())
        client.tickSize(10000, VOLUME_SIZE_TICK, 1234)

        quote = client.quote_states["AAPL"].to_quote("ibkr_readonly")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.symbol, "AAPL")
        self.assertEqual(quote.bid, 100.0)
        self.assertEqual(quote.ask, 100.1)
        self.assertEqual(quote.last, 100.05)
        self.assertEqual(quote.volume, 1234)
        self.assertTrue(client.quotes_ready.is_set())

    def test_close_price_can_create_quote_when_last_is_missing(self) -> None:
        client = IbkrReadOnlyQuoteClient({10000: "MSFT"})

        client.tickPrice(10000, CLOSE_PRICE_TICK, 350.0, object())

        quote = client.quote_states["MSFT"].to_quote("ibkr_readonly")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.last, 350.0)
        self.assertEqual(quote.close, 350.0)

    def test_delayed_tick_callbacks_build_normalized_quote(self) -> None:
        client = IbkrReadOnlyQuoteClient({10000: "QQQ"})

        client.tickPrice(10000, DELAYED_BID_PRICE_TICK, 500.0, object())
        client.tickPrice(10000, DELAYED_ASK_PRICE_TICK, 500.2, object())
        client.tickPrice(10000, DELAYED_LAST_PRICE_TICK, 500.1, object())

        quote = client.quote_states["QQQ"].to_quote("ibkr_readonly")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.bid, 500.0)
        self.assertEqual(quote.ask, 500.2)
        self.assertEqual(quote.last, 500.1)

    def test_simulation_source_can_build_ibkr_readonly_provider(self) -> None:
        source = quote_source(
            StrategySimulationConfig(
                symbols=["AAPL"],
                source="ibkr-readonly",
                ibkr_host="127.0.0.1",
                ibkr_port=7497,
                ibkr_client_id=500,
                ibkr_market_data_type=3,
                ibkr_exchange="IEX",
            )
        )

        self.assertIsInstance(source, IbkrReadOnlyQuoteSource)
        self.assertEqual(source._exchange, "IEX")

    def test_stock_contract_can_target_iex(self) -> None:
        contract = IbkrReadOnlyQuoteSource._stock_contract("MSFT", "IEX")

        self.assertEqual(contract.symbol, "MSFT")
        self.assertEqual(contract.exchange, "IEX")
        self.assertEqual(contract.secType, "STK")


if __name__ == "__main__":
    unittest.main()
