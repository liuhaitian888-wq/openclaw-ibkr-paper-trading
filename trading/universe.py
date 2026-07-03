import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from trading.strategy import CandidateProfile, FilterResult, ValuePoolFilter


DEFAULT_UNIVERSE_FILE = Path(__file__).resolve().parent.parent / "data" / "us_equity_universe.csv"


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    enabled: bool = True
    tags: Tuple[str, ...] = ()
    profile: Optional[CandidateProfile] = None


@dataclass(frozen=True)
class UniverseSelectionConfig:
    allow_unknown_fundamentals: bool = True
    include_tags: Tuple[str, ...] = ()
    exclude_tags: Tuple[str, ...] = ()
    include_sectors: Tuple[str, ...] = ()
    exclude_sectors: Tuple[str, ...] = ()
    max_symbols: int = 0


@dataclass(frozen=True)
class UniverseSelection:
    symbols: List[str]
    records: List[Dict[str, object]]


def load_universe(path: Path = DEFAULT_UNIVERSE_FILE) -> List[UniverseEntry]:
    if not path.exists():
        raise FileNotFoundError(f"universe file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [_entry_from_row(row) for row in rows]


def select_universe(
    entries: Sequence[UniverseEntry],
    value_filter: ValuePoolFilter,
    config: UniverseSelectionConfig = UniverseSelectionConfig(),
    requested_symbols: Optional[Iterable[str]] = None,
    gateway_allowed_symbols: Optional[Iterable[str]] = None,
) -> UniverseSelection:
    requested = _clean_symbol_set(requested_symbols)
    allowed = _clean_symbol_set(gateway_allowed_symbols)
    include_tags = {item.lower() for item in config.include_tags}
    exclude_tags = {item.lower() for item in config.exclude_tags}
    include_sectors = {item.lower() for item in config.include_sectors}
    exclude_sectors = {item.lower() for item in config.exclude_sectors}

    selected_symbols: List[str] = []
    records: List[Dict[str, object]] = []
    for entry in entries:
        symbol = entry.symbol.upper()
        reasons: List[str] = []
        if not entry.enabled:
            reasons.append("disabled in universe")
        if requested and symbol not in requested:
            reasons.append("not requested")
        if allowed and symbol not in allowed:
            reasons.append("not in gateway allowlist")
        lower_tags = {tag.lower() for tag in entry.tags}
        sector = entry.sector.lower()
        if include_tags and lower_tags.isdisjoint(include_tags):
            reasons.append("missing required tag")
        if exclude_tags and not lower_tags.isdisjoint(exclude_tags):
            reasons.append("excluded tag")
        if include_sectors and sector not in include_sectors:
            reasons.append("sector not included")
        if exclude_sectors and sector in exclude_sectors:
            reasons.append("sector excluded")

        filter_result: Optional[FilterResult] = None
        if entry.profile is None:
            if not config.allow_unknown_fundamentals:
                reasons.append("missing fundamental profile")
        elif "index-etf" not in lower_tags:
            filter_result = value_filter.evaluate(entry.profile)
            if not filter_result.approved:
                reasons.extend(filter_result.reasons)

        approved = not reasons
        if approved and (config.max_symbols <= 0 or len(selected_symbols) < config.max_symbols):
            selected_symbols.append(symbol)
        elif approved:
            approved = False
            reasons.append("selection max_symbols reached")

        records.append(
            {
                "symbol": symbol,
                "name": entry.name,
                "exchange": entry.exchange,
                "sector": entry.sector,
                "tags": list(entry.tags),
                "approved": approved,
                "reasons": reasons,
                "score": None if filter_result is None else filter_result.score,
                "score_breakdown": None if filter_result is None else filter_result.score_breakdown,
            }
        )
    return UniverseSelection(selected_symbols, records)


def default_universe_symbols(path: Path = DEFAULT_UNIVERSE_FILE) -> List[str]:
    return [entry.symbol for entry in load_universe(path) if entry.enabled]


def symbols_csv(symbols: Sequence[str]) -> str:
    return ",".join(dict.fromkeys(symbol.upper() for symbol in symbols if symbol.strip()))


def _entry_from_row(row: Dict[str, str]) -> UniverseEntry:
    symbol = row.get("symbol", "").strip().upper()
    tags = tuple(
        tag.strip()
        for tag in row.get("tags", "").split(";")
        if tag.strip()
    )
    profile = CandidateProfile(
        symbol=symbol,
        pe_ratio=_float_or_none(row.get("pe_ratio")),
        forward_pe=_float_or_none(row.get("forward_pe")),
        peg_ratio=_float_or_none(row.get("peg_ratio")),
        debt_to_equity=_float_or_none(row.get("debt_to_equity")),
        revenue_growth_yoy=_float_or_none(row.get("revenue_growth_yoy")),
        gross_margin=_float_or_none(row.get("gross_margin")),
        operating_margin=_float_or_none(row.get("operating_margin")),
        return_on_invested_capital=_float_or_none(row.get("return_on_invested_capital")),
        free_cash_flow_positive=_bool_or_true(row.get("free_cash_flow_positive")),
        earnings_positive=_bool_or_true(row.get("earnings_positive")),
        analyst_revision_positive=_bool_or_none(row.get("analyst_revision_positive")),
        average_volume=_int_or_none(row.get("average_volume")),
    )
    has_fundamentals = any(
        value is not None
        for value in (
            profile.pe_ratio,
            profile.forward_pe,
            profile.peg_ratio,
            profile.debt_to_equity,
            profile.revenue_growth_yoy,
            profile.gross_margin,
            profile.operating_margin,
            profile.return_on_invested_capital,
        )
    )
    return UniverseEntry(
        symbol=symbol,
        name=row.get("name", "").strip(),
        exchange=row.get("exchange", "").strip().upper(),
        sector=row.get("sector", "").strip(),
        enabled=_bool_or_true(row.get("enabled")),
        tags=tags,
        profile=profile if has_fundamentals else None,
    )


def _clean_symbol_set(values: Optional[Iterable[str]]) -> Set[str]:
    if values is None:
        return set()
    return {value.strip().upper() for value in values if value and value.strip()}


def _float_or_none(value: Optional[str]) -> Optional[float]:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int_or_none(value: Optional[str]) -> Optional[int]:
    if value is None or not value.strip():
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _bool_or_true(value: Optional[str]) -> bool:
    if value is None or not value.strip():
        return True
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _bool_or_none(value: Optional[str]) -> Optional[bool]:
    if value is None or not value.strip():
        return None
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}
