import csv
import json
import time
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Generic, Iterable, Iterator, List, Optional, Protocol, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Quote:
    symbol: str
    last: float
    timestamp: datetime
    source: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None

    def age_ms(self, now: Optional[datetime] = None) -> float:
        current = now or datetime.now(timezone.utc)
        return round((current - self.timestamp).total_seconds() * 1000, 3)

    @property
    def midpoint(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return max(0.0, self.ask - self.bid)


@dataclass(frozen=True)
class Bar:
    symbol: str
    interval_seconds: int
    started_at: datetime
    ended_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class QuoteSource(Protocol):
    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        raise NotImplementedError


class InMemoryQuoteCache:
    def __init__(self) -> None:
        self._quotes: Dict[str, Quote] = {}

    def update(self, quote: Quote) -> None:
        self._quotes[quote.symbol.upper()] = quote

    def update_many(self, quotes: Iterable[Quote]) -> None:
        for quote in quotes:
            self.update(quote)

    def get(self, symbol: str) -> Optional[Quote]:
        return self._quotes.get(symbol.upper())

    def is_fresh(self, symbol: str, max_age_ms: float) -> bool:
        quote = self.get(symbol)
        return quote is not None and quote.age_ms() <= max_age_ms

    def snapshot(self) -> Dict[str, Quote]:
        return dict(self._quotes)


class RingBuffer(Generic[T]):
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._items: List[T] = []

    def append(self, item: T) -> None:
        self._items.append(item)
        overflow = len(self._items) - self._capacity
        if overflow > 0:
            del self._items[:overflow]

    def replace_latest(self, item: T) -> None:
        if self._items:
            self._items[-1] = item
        else:
            self._items.append(item)

    def latest(self) -> Optional[T]:
        if not self._items:
            return None
        return self._items[-1]

    def values(self) -> List[T]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


class SymbolRingBuffers(Generic[T]):
    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._buffers: Dict[str, RingBuffer[T]] = {}

    def append(self, symbol: str, item: T) -> None:
        self._buffer(symbol).append(item)

    def replace_latest(self, symbol: str, item: T) -> None:
        self._buffer(symbol).replace_latest(item)

    def latest(self, symbol: str) -> Optional[T]:
        buffer = self._buffers.get(symbol.upper())
        return None if buffer is None else buffer.latest()

    def values(self, symbol: str) -> List[T]:
        buffer = self._buffers.get(symbol.upper())
        return [] if buffer is None else buffer.values()

    def snapshot(self) -> Dict[str, List[T]]:
        return {
            symbol: buffer.values()
            for symbol, buffer in self._buffers.items()
        }

    def _buffer(self, symbol: str) -> RingBuffer[T]:
        clean_symbol = symbol.upper()
        if clean_symbol not in self._buffers:
            self._buffers[clean_symbol] = RingBuffer(self._capacity)
        return self._buffers[clean_symbol]


class RotatingSymbolPool:
    def __init__(self, symbols: Sequence[str], batch_size: int) -> None:
        clean_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not clean_symbols:
            raise ValueError("symbols must not be empty")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._symbols = list(dict.fromkeys(clean_symbols))
        self._batch_size = batch_size
        self._index = 0

    @property
    def symbols(self) -> List[str]:
        return list(self._symbols)

    def next_batch(self) -> List[str]:
        if self._batch_size >= len(self._symbols):
            self._index = 0
            return list(self._symbols)

        batch = []
        for offset in range(self._batch_size):
            batch.append(self._symbols[(self._index + offset) % len(self._symbols)])
        self._index = (self._index + self._batch_size) % len(self._symbols)
        return batch


class BarBuilder:
    def __init__(self, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._active: Dict[str, Bar] = {}

    def update(self, quote: Quote) -> Optional[Bar]:
        symbol = quote.symbol.upper()
        bucket_start = _bucket_start(quote.timestamp, self.interval_seconds)
        active = self._active.get(symbol)
        if active is None:
            self._active[symbol] = self._new_bar(quote, bucket_start)
            return None
        if active.started_at != bucket_start:
            closed = active
            self._active[symbol] = self._new_bar(quote, bucket_start)
            return closed
        self._active[symbol] = Bar(
            symbol=symbol,
            interval_seconds=self.interval_seconds,
            started_at=active.started_at,
            ended_at=quote.timestamp,
            open=active.open,
            high=max(active.high, quote.last),
            low=min(active.low, quote.last),
            close=quote.last,
            volume=active.volume + (quote.volume or 0),
        )
        return None

    def active_bar(self, symbol: str) -> Optional[Bar]:
        return self._active.get(symbol.upper())

    def _new_bar(self, quote: Quote, started_at: datetime) -> Bar:
        return Bar(
            symbol=quote.symbol.upper(),
            interval_seconds=self.interval_seconds,
            started_at=started_at,
            ended_at=quote.timestamp,
            open=quote.last,
            high=quote.last,
            low=quote.last,
            close=quote.last,
            volume=quote.volume or 0,
        )


class SimulatedQuoteSource:
    def __init__(self, prices: Dict[str, Sequence[float]], source: str = "simulated") -> None:
        self._prices = {symbol.upper(): list(values) for symbol, values in prices.items()}
        self._indexes = {symbol.upper(): 0 for symbol in prices}
        self._source = source

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        now = datetime.now(timezone.utc)
        quotes = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            values = self._prices.get(symbol)
            if not values:
                continue
            index = self._indexes[symbol]
            price = float(values[min(index, len(values) - 1)])
            self._indexes[symbol] = index + 1
            quotes.append(
                Quote(
                    symbol=symbol,
                    last=price,
                    bid=round(price * 0.9998, 4),
                    ask=round(price * 1.0002, 4),
                    close=price,
                    timestamp=now,
                    source=self._source,
                    volume=100,
                )
            )
        return quotes


class StooqDelayedQuoteSource:
    """Keyless delayed quote source for early experiments.

    This is a polling source, not true low-latency streaming. Use it for
    framework testing and research mode, not final fast execution.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        if not symbols:
            return []
        self.last_errors = []
        quotes = []
        for symbol in symbols:
            stooq_symbol = f"{symbol.lower()}.us"
            request = urllib.request.Request(
                f"https://stooq.com/q/l/?s={stooq_symbol}&f=sd2t2ohlcv&h&e=csv",
                headers={"User-Agent": "openclaw-research-gateway/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    rows = csv.DictReader(response.read().decode("utf-8").splitlines())
                    quotes.extend(
                        quote
                        for row in rows
                        if (quote := self._row_to_quote(row)) is not None
                    )
            except (HTTPError, URLError, TimeoutError) as exc:
                self.last_errors.append(f"{symbol.upper()}: {exc}")
        return quotes

    @staticmethod
    def _row_to_quote(row: Dict[str, str]) -> Optional[Quote]:
        symbol = row.get("Symbol", "").split(".")[0].upper()
        close = _float_or_none(row.get("Close", ""))
        if not symbol or close is None:
            return None
        volume = _int_or_none(row.get("Volume", ""))
        return Quote(
            symbol=symbol,
            last=close,
            close=close,
            timestamp=datetime.now(timezone.utc),
            source="stooq_delayed",
            volume=volume,
        )


class YahooDelayedQuoteSource:
    """Keyless Yahoo chart quote source for bootstrap polling.

    This is a public endpoint and should be treated as delayed/best-effort data,
    not a guaranteed execution-grade feed.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        self.last_errors = []
        quotes = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            request = urllib.request.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m",
                headers={"User-Agent": "openclaw-research-gateway/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    quote = self._quote_from_chart_payload(symbol, payload)
                    if quote is not None:
                        quotes.append(quote)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                self.last_errors.append(f"{symbol}: {exc}")
        return quotes

    @staticmethod
    def _quote_from_chart_payload(symbol: str, payload: Dict[str, object]) -> Optional[Quote]:
        quotes = YahooDelayedQuoteSource._quotes_from_chart_payload(
            symbol,
            payload,
            source="yahoo_delayed",
        )
        return quotes[-1] if quotes else None

    @staticmethod
    def _quotes_from_chart_payload(
        symbol: str,
        payload: Dict[str, object],
        source: str,
    ) -> List[Quote]:
        chart = payload.get("chart")
        if not isinstance(chart, dict):
            return []
        result = chart.get("result")
        if not isinstance(result, list) or not result:
            return []
        item = result[0]
        if not isinstance(item, dict):
            return []
        timestamps = item.get("timestamp")
        indicators = item.get("indicators")
        if not isinstance(timestamps, list) or not timestamps:
            return []
        if not isinstance(indicators, dict):
            return []
        quote_items = indicators.get("quote")
        if not isinstance(quote_items, list) or not quote_items:
            return []
        quote_item = quote_items[0]
        if not isinstance(quote_item, dict):
            return []
        closes = quote_item.get("close")
        volumes = quote_item.get("volume")
        if not isinstance(closes, list):
            return []

        quotes = []
        for index, close in enumerate(closes):
            if index >= len(timestamps):
                break
            close = closes[index]
            if isinstance(close, (int, float)):
                volume = None
                if isinstance(volumes, list) and index < len(volumes):
                    volume = volumes[index]
                quotes.append(
                    Quote(
                        symbol=symbol.upper(),
                        last=float(close),
                        close=float(close),
                        timestamp=datetime.fromtimestamp(float(timestamps[index]), tz=timezone.utc),
                        source=source,
                        volume=int(volume) if isinstance(volume, (int, float)) else None,
                    )
                )
        return quotes


class YahooChartReplayQuoteSource:
    """Replay recent Yahoo 1-minute chart bars as a moving quote source.

    This is for simulation/dashboard movement only. It is historical replay, not
    a real-time execution feed.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._quotes_by_symbol: Dict[str, List[Quote]] = {}
        self._indexes: Dict[str, int] = {}
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        self.last_errors = []
        quotes = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            if symbol not in self._quotes_by_symbol:
                self._load_symbol(symbol)
            series = self._quotes_by_symbol.get(symbol, [])
            if not series:
                continue
            index = self._indexes.get(symbol, 0)
            quotes.append(series[min(index, len(series) - 1)])
            self._indexes[symbol] = index + 1
        return quotes

    def _load_symbol(self, symbol: str) -> None:
        request = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m",
            headers={"User-Agent": "openclaw-research-gateway/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                series = YahooDelayedQuoteSource._quotes_from_chart_payload(
                    symbol,
                    payload,
                    source="yahoo_replay",
                )
                self._quotes_by_symbol[symbol] = series[-120:] if len(series) > 120 else series
                self._indexes[symbol] = 0
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            self._quotes_by_symbol[symbol] = []
            self.last_errors.append(f"{symbol}: {exc}")


def quote_stream(
    source: QuoteSource,
    symbols: Sequence[str],
    poll_seconds: float,
) -> Iterator[List[Quote]]:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    while True:
        yield source.get_quotes(symbols)
        time.sleep(poll_seconds)


def _bucket_start(timestamp: datetime, interval_seconds: int) -> datetime:
    seconds = int(timestamp.timestamp())
    return datetime.fromtimestamp(
        seconds - (seconds % interval_seconds),
        tz=timezone.utc,
    )


def _float_or_none(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
