import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from trading.market_data import Quote
from trading.market_session import classify_streaming_bid_ask_gap


BID_PRICE_TICK = 1
ASK_PRICE_TICK = 2
LAST_PRICE_TICK = 4
CLOSE_PRICE_TICK = 9
VOLUME_SIZE_TICK = 8

MARKET_DATA_TYPES = {
    1: "live",
    2: "frozen",
    3: "delayed",
    4: "delayed_frozen",
}

LOGGER = logging.getLogger(__name__)


@dataclass
class StreamingQuoteState:
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    timestamp: Optional[datetime] = None
    bid_timestamp: Optional[datetime] = None
    ask_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    market_data_type: Optional[int] = None
    errors: List[str] = field(default_factory=list)

    def to_quote(self, source: str = "ibkr_streaming") -> Optional[Quote]:
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
            timestamp=self.timestamp or datetime.now(timezone.utc),
            source=source,
        )

    def age_ms(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.timestamp is None:
            return None
        current = now or datetime.now(timezone.utc)
        return round((current - self.timestamp).total_seconds() * 1000, 3)

    def field_age_ms(self, field: str, now: Optional[datetime] = None) -> Optional[float]:
        timestamp = {
            "bid": self.bid_timestamp,
            "ask": self.ask_timestamp,
            "last": self.last_timestamp,
        }.get(field)
        if timestamp is None:
            return None
        current = now or datetime.now(timezone.utc)
        return round((current - timestamp).total_seconds() * 1000, 3)

    def market_data_type_name(self) -> Optional[str]:
        if self.market_data_type is None:
            return None
        return MARKET_DATA_TYPES.get(self.market_data_type, str(self.market_data_type))


class IbkrStreamingQuoteClient(EWrapper, EClient):
    def __init__(self, ticker_id_to_symbol: Dict[int, str]) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.ticker_id_to_symbol = dict(ticker_id_to_symbol)
        self.quote_states: Dict[str, StreamingQuoteState] = {
            symbol: StreamingQuoteState(symbol=symbol)
            for symbol in ticker_id_to_symbol.values()
        }
        self.errors: List[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS streaming market-data thread stopped during disconnect: {exc}")
                return
            raise

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        message = f"request={reqId}, details={args}"
        self.errors.append(message)
        state = self._state(reqId)
        if state is not None:
            state.errors.append(message)
        _log_event("subscription_error", ticker_id=reqId, symbol=None if state is None else state.symbol, error=message)

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: object) -> None:  # noqa: N802,E501
        if price <= 0:
            return
        state = self._state(reqId)
        if state is None:
            return
        if tickType == BID_PRICE_TICK:
            state.bid = float(price)
            state.bid_timestamp = datetime.now(timezone.utc)
        elif tickType == ASK_PRICE_TICK:
            state.ask = float(price)
            state.ask_timestamp = datetime.now(timezone.utc)
        elif tickType == LAST_PRICE_TICK:
            state.last = float(price)
            state.last_timestamp = datetime.now(timezone.utc)
        elif tickType == CLOSE_PRICE_TICK:
            state.close = float(price)
        else:
            return
        state.timestamp = datetime.now(timezone.utc)
        _log_event("quote_update", ticker_id=reqId, symbol=state.symbol, tick_type=tickType, price=float(price))

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        state = self._state(reqId)
        if state is None:
            return
        if tickType == VOLUME_SIZE_TICK and size >= 0:
            state.volume = int(size)

    def tickString(self, reqId: int, tickType: int, value: str) -> None:  # noqa: N802
        state = self._state(reqId)
        if state is None:
            return
        _log_event("quote_update", ticker_id=reqId, symbol=state.symbol, tick_type=tickType, value=value)

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802,N803
        state = self._state(reqId)
        if state is None:
            return
        state.market_data_type = int(marketDataType)
        _log_event(
            "quote_update",
            ticker_id=reqId,
            symbol=state.symbol,
            market_data_type=state.market_data_type_name(),
        )

    def _state(self, ticker_id: int) -> Optional[StreamingQuoteState]:
        symbol = self.ticker_id_to_symbol.get(ticker_id)
        if symbol is None:
            return None
        return self.quote_states[symbol]


class IbkrStreamingQuoteSource:
    """Read-only IBKR Level I streaming quote source for a small symbol set."""

    def __init__(
        self,
        *,
        symbols: Sequence[str],
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 32,
        stale_ms: float = 3000.0,
        max_symbols: int = 3,
        market_data_type: int = 1,
        exchange: str = "SMART",
        client_factory: Callable[[Dict[int, str]], IbkrStreamingQuoteClient] = IbkrStreamingQuoteClient,
        ticker_id_start: int = 30_000,
    ) -> None:
        self.symbols, self.configuration_errors = _clean_symbols(symbols, max_symbols)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._stale_ms = stale_ms
        self._market_data_type = market_data_type
        self._exchange = exchange.strip().upper() or "SMART"
        self._ticker_id_to_symbol = {
            ticker_id_start + index: symbol
            for index, symbol in enumerate(self.symbols)
        }
        self._client = client_factory(self._ticker_id_to_symbol)
        self._thread: Optional[threading.Thread] = None
        self._started = False

    def start(self, timeout: float = 5.0) -> bool:
        if not self.symbols:
            self._client.errors.extend(self.configuration_errors or ["no streaming symbols configured"])
            return False
        _log_event("streaming_started", symbols=self.symbols, host=self._host, port=self._port, client_id=self._client_id)
        try:
            self._client.connect(self._host, self._port, clientId=self._client_id)
            self._thread = threading.Thread(target=self._client.run_loop, daemon=True)
            self._thread.start()
            if not self._client.ready.wait(timeout):
                self._client.errors.append("TWS streaming market-data handshake timed out")
                return False
            self._client.reqMarketDataType(self._market_data_type)
            for ticker_id, symbol in self._ticker_id_to_symbol.items():
                self._client.reqMktData(
                    ticker_id,
                    self._stock_contract(symbol, self._exchange),
                    "",
                    False,
                    False,
                    [],
                )
                _log_event("subscription_requested", ticker_id=ticker_id, symbol=symbol, snapshot=False)
            self._started = True
            return True
        except Exception as exc:
            self._client.errors.append(f"IBKR streaming quote source failed: {exc}")
            return False

    def stop(self) -> None:
        for ticker_id in self._ticker_id_to_symbol:
            try:
                self._client.cancelMktData(ticker_id)
            except Exception as exc:
                self._client.errors.append(f"cancelMktData failed for {ticker_id}: {exc}")
        if self._client.isConnected():
            self._client.disconnect()
        self._started = False
        _log_event("streaming_stopped", symbols=self.symbols)

    def get_latest_quotes(self) -> Dict[str, Quote]:
        return {
            symbol: quote
            for symbol, state in self._client.quote_states.items()
            if (quote := state.to_quote()) is not None
        }

    def get_quote(self, symbol: str) -> Optional[Quote]:
        state = self._client.quote_states.get(symbol.strip().upper())
        if state is None:
            return None
        return state.to_quote()

    def quote_age_ms(self, symbol: str) -> Optional[float]:
        state = self._client.quote_states.get(symbol.strip().upper())
        if state is None:
            return None
        return state.age_ms()

    def is_stale(self, symbol: str) -> bool:
        age = self.quote_age_ms(symbol)
        stale = age is None or age > self._stale_ms
        if stale:
            _log_event("quote_stale", symbol=symbol.strip().upper(), age_ms=age, stale_ms=self._stale_ms)
        return stale

    def stale_symbols(self) -> List[str]:
        return [symbol for symbol in self.symbols if self.is_stale(symbol)]

    @property
    def errors(self) -> List[str]:
        return list(dict.fromkeys(self.configuration_errors + self._client.errors))

    @property
    def active(self) -> bool:
        return self._started

    def report(self) -> Dict[str, object]:
        quotes = {}
        for symbol, state in self._client.quote_states.items():
            quote = state.to_quote()
            if quote is None:
                continue
            quotes[symbol] = {
                "bid": quote.bid,
                "ask": quote.ask,
                "last": quote.last,
                "close": quote.close,
                "volume": quote.volume,
                "age_ms": quote.age_ms(),
                "bid_age_ms": state.field_age_ms("bid"),
                "ask_age_ms": state.field_age_ms("ask"),
                "last_age_ms": state.field_age_ms("last"),
                "market_data_type": state.market_data_type_name(),
                "market_data_type_raw": state.market_data_type,
                "timestamp": quote.timestamp.isoformat(),
                "source": quote.source,
            }
        return {
            "streaming_symbols": list(self.symbols),
            "streaming_quote_count": len(quotes),
            "streaming_stale_symbols": self.stale_symbols(),
            "streaming_errors": self.errors,
            "streaming_quotes": quotes,
        }

    def diagnostics(self) -> Dict[str, object]:
        now = datetime.now(timezone.utc)
        rows = []
        for symbol, state in self._client.quote_states.items():
            market_type = state.market_data_type
            bid_age = state.field_age_ms("bid", now)
            ask_age = state.field_age_ms("ask", now)
            last_age = state.field_age_ms("last", now)
            spread_pct = None
            if state.bid is not None and state.ask is not None:
                reference = state.last or ((state.bid + state.ask) / 2)
                if reference and reference > 0:
                    spread_pct = round((state.ask - state.bid) / reference, 6)
            blocked = streaming_blocked_reason(state, started=self._started)
            rows.append(
                {
                    "symbol": symbol,
                    "contract_qualified": True,
                    "streaming_requested": self._started,
                    "streaming_request_ok": self._started and not state.errors,
                    "market_data_type": market_type,
                    "market_data_type_name": state.market_data_type_name() or "unknown",
                    "live_data_confirmed": market_type == 1,
                    "bid_received": state.bid is not None,
                    "ask_received": state.ask is not None,
                    "last_received": state.last is not None,
                    "bid": state.bid,
                    "ask": state.ask,
                    "last": state.last,
                    "bid_age_sec": None if bid_age is None else bid_age / 1000.0,
                    "ask_age_sec": None if ask_age is None else ask_age / 1000.0,
                    "last_age_sec": None if last_age is None else last_age / 1000.0,
                    "spread_pct": spread_pct,
                    "snapshot_request_used": False,
                    "regulatory_snapshot_used": False,
                    "blocked_reason": blocked,
                    "errors": list(state.errors),
                }
            )
        return {
            "timestamp": now.isoformat(),
            "source": "ibkr_streaming_diagnostics",
            "symbols": list(self.symbols),
            "rows": rows,
            "errors": self.errors,
        }

    @staticmethod
    def _stock_contract(symbol: str, exchange: str = "SMART") -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = exchange
        contract.currency = "USD"
        return contract


def _clean_symbols(symbols: Sequence[str], max_symbols: int) -> tuple[tuple[str, ...], List[str]]:
    errors = []
    clean = [
        symbol.strip().upper()
        for symbol in symbols
        if symbol and symbol.strip()
    ]
    unique = list(dict.fromkeys(clean))
    valid = [
        symbol
        for symbol in unique
        if symbol.replace(".", "").replace("-", "").isalnum()
    ]
    invalid = [symbol for symbol in unique if symbol not in valid]
    if invalid:
        errors.append("invalid streaming symbols ignored: " + ",".join(invalid))
    limit = max(0, max_symbols)
    if limit and len(valid) > limit:
        errors.append(f"streaming symbols truncated to STREAMING_MAX_SYMBOLS={limit}")
        valid = valid[:limit]
    return tuple(valid), errors


def _log_event(event: str, **payload: object) -> None:
    LOGGER.info(json.dumps({"event": event, **payload}, sort_keys=True))


def streaming_blocked_reason(state: StreamingQuoteState, *, started: bool) -> str:
    if not started:
        return "streaming_not_requested"
    text = " ".join(state.errors).lower()
    if "not connected" in text or "handshake" in text:
        return "IBKR_not_connected"
    if "contract" in text:
        return "contract_qualification_failed"
    if "permission" in text or "not subscribed" in text or "no market data" in text:
        return "no_market_data_subscription"
    if state.market_data_type == 3:
        return "delayed_data_only"
    if state.market_data_type in {2, 4}:
        return "frozen_data_only"
    if state.bid is None or state.ask is None:
        if state.last is not None or state.close is not None:
            return classify_streaming_bid_ask_gap(
                last_received=state.last is not None,
                close_received=state.close is not None,
            )
        return "outside_session_no_quote"
    return ""
