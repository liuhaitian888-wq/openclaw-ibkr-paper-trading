import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from trading.market_data import Quote


BID_PRICE_TICK = 1
ASK_PRICE_TICK = 2
LAST_PRICE_TICK = 4
CLOSE_PRICE_TICK = 9
VOLUME_SIZE_TICK = 8
DELAYED_BID_PRICE_TICK = 66
DELAYED_ASK_PRICE_TICK = 67
DELAYED_LAST_PRICE_TICK = 68
DELAYED_CLOSE_PRICE_TICK = 75
DELAYED_VOLUME_SIZE_TICK = 74


@dataclass
class _QuoteState:
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_quote(self, source: str) -> Optional[Quote]:
        price = self.last if self.last is not None else self.close
        if price is None:
            if self.bid is not None and self.ask is not None:
                price = (self.bid + self.ask) / 2
            else:
                return None
        return Quote(
            symbol=self.symbol,
            last=price,
            bid=self.bid,
            ask=self.ask,
            close=self.close,
            volume=self.volume,
            timestamp=self.timestamp,
            source=source,
        )


class IbkrReadOnlyQuoteClient(EWrapper, EClient):
    def __init__(self, req_id_to_symbol: Dict[int, str]) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.quotes_ready = threading.Event()
        self.errors: List[str] = []
        self.req_id_to_symbol = dict(req_id_to_symbol)
        self.quote_states: Dict[str, _QuoteState] = {
            symbol: _QuoteState(symbol=symbol)
            for symbol in req_id_to_symbol.values()
        }

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS market-data thread stopped during disconnect: {exc}")
                return
            raise

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        if any("Displaying delayed market data" in str(item) for item in args):
            return
        self.errors.append(f"request={reqId}, details={args}")

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: object) -> None:  # noqa: N802,E501
        if price <= 0:
            return
        state = self._state(reqId)
        if state is None:
            return
        if tickType in {BID_PRICE_TICK, DELAYED_BID_PRICE_TICK}:
            state.bid = float(price)
        elif tickType in {ASK_PRICE_TICK, DELAYED_ASK_PRICE_TICK}:
            state.ask = float(price)
        elif tickType in {LAST_PRICE_TICK, DELAYED_LAST_PRICE_TICK}:
            state.last = float(price)
        elif tickType in {CLOSE_PRICE_TICK, DELAYED_CLOSE_PRICE_TICK}:
            state.close = float(price)
        else:
            return
        state.timestamp = datetime.now(timezone.utc)
        self._mark_ready_if_possible()

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        state = self._state(reqId)
        if state is None:
            return
        if tickType in {VOLUME_SIZE_TICK, DELAYED_VOLUME_SIZE_TICK} and size >= 0:
            state.volume = int(size)

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        self._mark_ready_if_possible()

    def _state(self, req_id: int) -> Optional[_QuoteState]:
        symbol = self.req_id_to_symbol.get(req_id)
        if symbol is None:
            return None
        return self.quote_states[symbol]

    def _mark_ready_if_possible(self) -> None:
        if any(state.to_quote("ibkr_readonly") for state in self.quote_states.values()):
            self.quotes_ready.set()


class IbkrReadOnlyQuoteSource:
    """Read-only IBKR quote source.

    This class only requests market data. It does not expose order-placement
    methods and should remain separate from the execution adapter.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 31,
        timeout: float = 5.0,
        snapshot: bool = True,
        market_data_type: int = 1,
        exchange: str = "SMART",
        primary_exchange: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._snapshot = snapshot
        self._market_data_type = market_data_type
        self._exchange = exchange.strip().upper() or "SMART"
        self._primary_exchange = primary_exchange.strip().upper()
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        clean_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not clean_symbols:
            return []

        req_id_to_symbol = {
            index + 10_000: symbol
            for index, symbol in enumerate(clean_symbols)
        }
        client = IbkrReadOnlyQuoteClient(req_id_to_symbol)
        try:
            client.connect(self._host, self._port, clientId=self._client_id)
            threading.Thread(target=client.run_loop, daemon=True).start()
            if not client.ready.wait(self._timeout):
                self.last_errors = list(client.errors) + ["TWS API handshake timed out"]
                return []
            client.reqMarketDataType(self._market_data_type)
            for req_id, symbol in req_id_to_symbol.items():
                client.reqMktData(
                    req_id,
                    self._stock_contract(symbol, self._exchange, self._primary_exchange),
                    "",
                    self._snapshot,
                    False,
                    [],
                )
            self._wait_for_quotes(client, len(clean_symbols))
            if self._snapshot:
                time.sleep(0.1)
            self.last_errors = list(client.errors)
            return [
                quote
                for state in client.quote_states.values()
                if (quote := state.to_quote("ibkr_readonly")) is not None
            ]
        except Exception as exc:
            self.last_errors = list(client.errors) + [f"IBKR read-only quote request failed: {exc}"]
            return []
        finally:
            for error in client.errors:
                if error not in self.last_errors:
                    self.last_errors.append(error)
            for req_id in req_id_to_symbol:
                try:
                    client.cancelMktData(req_id)
                except Exception:
                    pass
            if client.isConnected():
                client.disconnect()

    @staticmethod
    def _stock_contract(
        symbol: str,
        exchange: str = "SMART",
        primary_exchange: str = "",
    ) -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = exchange
        contract.currency = "USD"
        if primary_exchange:
            contract.primaryExchange = primary_exchange
        return contract

    def _wait_for_quotes(self, client: IbkrReadOnlyQuoteClient, expected_count: int) -> None:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            quote_count = sum(
                1
                for state in client.quote_states.values()
                if state.to_quote("ibkr_readonly") is not None
            )
            if quote_count >= expected_count:
                return
            time.sleep(0.05)


class ParallelIbkrReadOnlyQuoteSource:
    """Split quote batches across multiple read-only TWS client ids.

    TWS can reject duplicate client ids and market-data subscriptions are still
    governed by the account's IBKR limits, so this class is deliberately simple:
    bounded workers, deterministic chunks, no order methods.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 31,
        timeout: float = 5.0,
        snapshot: bool = True,
        market_data_type: int = 1,
        exchange: str = "SMART",
        primary_exchange: str = "",
        workers: int = 2,
        symbols_per_worker: int = 8,
        client_id_stride: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._snapshot = snapshot
        self._market_data_type = market_data_type
        self._exchange = exchange
        self._primary_exchange = primary_exchange
        self._workers = max(1, workers)
        self._symbols_per_worker = max(1, symbols_per_worker)
        self._client_id_stride = max(1, client_id_stride)
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        clean_symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
        if not clean_symbols:
            return []

        chunks = _chunks(clean_symbols, self._symbols_per_worker)
        worker_count = min(self._workers, len(chunks))
        quotes: List[Quote] = []
        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._source_for(index).get_quotes, chunk): index
                for index, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    quotes.extend(future.result())
                except Exception as exc:
                    errors.append(f"parallel IBKR worker {index} failed: {exc}")
        for index in range(len(chunks)):
            errors.extend(self._source_for(index).last_errors)
        self.last_errors = list(dict.fromkeys(errors))
        ranks = {symbol: index for index, symbol in enumerate(clean_symbols)}
        return sorted(quotes, key=lambda quote: ranks.get(quote.symbol, len(ranks)))

    def _source_for(self, index: int) -> IbkrReadOnlyQuoteSource:
        source = getattr(self, "_sources", None)
        if source is None:
            self._sources: Dict[int, IbkrReadOnlyQuoteSource] = {}
        if index not in self._sources:
            self._sources[index] = IbkrReadOnlyQuoteSource(
                host=self._host,
                port=self._port,
                client_id=self._client_id + index * self._client_id_stride,
                timeout=self._timeout,
                snapshot=self._snapshot,
                market_data_type=self._market_data_type,
                exchange=self._exchange,
                primary_exchange=self._primary_exchange,
            )
        return self._sources[index]


def _chunks(values: Sequence[str], size: int) -> List[List[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]
