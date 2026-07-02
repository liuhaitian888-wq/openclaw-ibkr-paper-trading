import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional


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
    audit_db: Path

    @classmethod
    def load(cls) -> "Settings":
        mode = os.getenv("TRADING_MODE", "DRY_RUN").strip().upper()
        if mode not in {"DRY_RUN", "PAPER"}:
            raise RuntimeError("TRADING_MODE must be DRY_RUN or PAPER")

        symbols = frozenset(
            item.strip().upper()
            for item in os.getenv("ALLOWED_SYMBOLS", "AAPL,MSFT,SPY").split(",")
            if item.strip()
        )
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
            audit_db=Path(os.getenv("AUDIT_DB", str(PROJECT_ROOT / "trading_audit.sqlite3"))),
        )
