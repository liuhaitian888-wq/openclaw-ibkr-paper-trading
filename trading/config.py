import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_or_create_api_key() -> str:
    configured = os.getenv("OPENCLAW_API_KEY")
    if configured:
        return configured

    secret_dir = PROJECT_ROOT / ".secrets"
    key_file = secret_dir / "openclaw_api_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    secret_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    key_file.write_text(value + "\n", encoding="utf-8")
    key_file.chmod(0o600)
    return value


def _load_optional_file_value(path: Optional[str]) -> str:
    if not path:
        return ""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8").strip()


def _load_allowed_symbols() -> FrozenSet[str]:
    configured = os.getenv("ALLOWED_SYMBOLS")
    if configured:
        return frozenset(
            item.strip().upper()
            for item in configured.split(",")
            if item.strip()
        )

    configured_file = os.getenv("ALLOWED_SYMBOLS_FILE")
    candidate_files = [
        Path(configured_file).expanduser() if configured_file else None,
        PROJECT_ROOT / "data" / "us_equity_universe.csv",
    ]
    for path in candidate_files:
        if path is None or not path.exists():
            continue
        symbols = _symbols_from_file(path)
        if symbols:
            return frozenset(symbols)
    return frozenset({"AAPL", "MSFT", "SPY"})


def _symbols_from_file(path: Path) -> FrozenSet[str]:
    symbols = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        first = line.split(",", 1)[0].strip().upper()
        if line_number == 0 and first == "SYMBOL":
            continue
        if first and first.replace(".", "").replace("-", "").isalnum():
            symbols.append(first)
    return frozenset(symbols)


def _read_symbol_tuple(name: str, default: str = "") -> Tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(
        dict.fromkeys(
            item.strip().upper()
            for item in raw.split(",")
            if item.strip()
        )
    )


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_host: str
    api_port: int
    trading_mode: str
    allow_tws_staging: bool
    allow_paper_transmit: bool
    allow_outside_rth: bool
    trading_kill_switch: bool
    trade_session_token: str
    tws_host: str
    tws_port: int
    tws_client_id: int
    tws_status_timeout: float
    allowed_symbols: FrozenSet[str]
    max_quantity: int
    max_order_value: float
    max_risk_per_order: float
    max_daily_notional_value: Optional[float]
    daily_notional_timezone: str
    streaming_market_data_enabled: bool
    streaming_symbols: Tuple[str, ...]
    streaming_max_symbols: int
    streaming_stale_ms: float
    streaming_tws_host: str
    streaming_tws_port: int
    streaming_client_id: int
    audit_db: Path

    @classmethod
    def load(cls) -> "Settings":
        mode = os.getenv("TRADING_MODE", "DRY_RUN").strip().upper()
        if mode not in {"DRY_RUN", "PAPER"}:
            raise RuntimeError("TRADING_MODE must be DRY_RUN or PAPER")

        symbols = _load_allowed_symbols()
        return cls(
            api_key=_load_or_create_api_key(),
            api_host=os.getenv("TRADING_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("TRADING_API_PORT", "8787")),
            trading_mode=mode,
            allow_tws_staging=_read_bool("ALLOW_TWS_STAGING"),
            allow_paper_transmit=_read_bool("ALLOW_PAPER_TRANSMIT"),
            allow_outside_rth=_read_bool("ALLOW_OUTSIDE_RTH"),
            trading_kill_switch=_read_bool("TRADING_KILL_SWITCH"),
            trade_session_token=os.getenv("TRADE_SESSION_TOKEN", "")
            or _load_optional_file_value(os.getenv("TRADE_SESSION_TOKEN_FILE")),
            tws_host=os.getenv("TWS_HOST", "127.0.0.1"),
            tws_port=int(os.getenv("TWS_PORT", "7497")),
            tws_client_id=int(os.getenv("TWS_CLIENT_ID", "22")),
            tws_status_timeout=float(os.getenv("TWS_STATUS_TIMEOUT", "2")),
            allowed_symbols=symbols,
            max_quantity=int(os.getenv("MAX_QUANTITY", "1")),
            max_order_value=float(os.getenv("MAX_ORDER_VALUE", "200")),
            max_risk_per_order=float(os.getenv("MAX_RISK_PER_ORDER", "10")),
            max_daily_notional_value=_read_optional_float("MAX_DAILY_NOTIONAL_VALUE"),
            daily_notional_timezone=os.getenv("DAILY_NOTIONAL_TIMEZONE", "Europe/Berlin"),
            streaming_market_data_enabled=_read_bool("STREAMING_MARKET_DATA_ENABLED"),
            streaming_symbols=_read_symbol_tuple("STREAMING_SYMBOLS", "AAPL,MSFT,NVDA"),
            streaming_max_symbols=int(os.getenv("STREAMING_MAX_SYMBOLS", "3")),
            streaming_stale_ms=float(os.getenv("STREAMING_STALE_MS", "3000")),
            streaming_tws_host=os.getenv("STREAMING_TWS_HOST", os.getenv("TWS_HOST", "127.0.0.1")),
            streaming_tws_port=int(os.getenv("STREAMING_TWS_PORT", os.getenv("TWS_PORT", "7497"))),
            streaming_client_id=int(os.getenv("STREAMING_CLIENT_ID", "32")),
            audit_db=Path(os.getenv("AUDIT_DB", str(PROJECT_ROOT / "trading_audit.sqlite3"))),
        )


def _read_optional_float(name: str) -> Optional[float]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    parsed = float(value)
    return parsed if parsed > 0 else None
