"""Record read-only IBKR paper account P&L samples over time.

This script never places orders. It connects to TWS, requests account-level P&L
and account summary values, then appends timestamped samples to CSV and JSONL.
"""

import argparse
import csv
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from trading.config import Settings


SUMMARY_TAGS = (
    "NetLiquidation,"
    "TotalCashValue,"
    "AvailableFunds,"
    "ExcessLiquidity,"
    "MaintMarginReq,"
    "BuyingPower,"
    "GrossPositionValue,"
    "UnrealizedPnL,"
    "RealizedPnL"
)


@dataclass(frozen=True)
class PnlSample:
    timestamp: str
    account: str
    currency: str
    daily_pnl: Optional[float]
    unrealized_pnl: Optional[float]
    realized_pnl: Optional[float]
    net_liquidation: Optional[float]
    total_cash_value: Optional[float]
    available_funds: Optional[float]
    excess_liquidity: Optional[float]
    maintenance_margin: Optional[float]
    buying_power: Optional[float]
    gross_position_value: Optional[float]
    portfolio_unrealized_pnl: Optional[float]
    portfolio_realized_pnl: Optional[float]
    open_positions: int
    source: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "account": self.account,
            "currency": self.currency,
            "daily_pnl": self.daily_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "net_liquidation": self.net_liquidation,
            "total_cash_value": self.total_cash_value,
            "available_funds": self.available_funds,
            "excess_liquidity": self.excess_liquidity,
            "maintenance_margin": self.maintenance_margin,
            "buying_power": self.buying_power,
            "gross_position_value": self.gross_position_value,
            "portfolio_unrealized_pnl": self.portfolio_unrealized_pnl,
            "portfolio_realized_pnl": self.portfolio_realized_pnl,
            "open_positions": self.open_positions,
            "source": self.source,
        }


class AccountPnlClient(EWrapper, EClient):
    def __init__(self, account: str, currency: str) -> None:
        EClient.__init__(self, self)
        self.account = account
        self.currency = currency
        self.ready = threading.Event()
        self.summary_ready = threading.Event()
        self.pnl_ready = threading.Event()
        self.portfolio_ready = threading.Event()
        self.accounts: List[str] = []
        self.summary: Dict[str, float] = {}
        self.pnl_values: Dict[str, float] = {}
        self.portfolio_values: Dict[str, Dict[str, float]] = {}
        self.errors: List[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item for item in accountsList.split(",") if item]

    def accountSummary(  # noqa: N802
        self,
        reqId: int,
        account: str,
        tag: str,
        value: str,
        currency: str,
    ) -> None:
        if self.account and account != self.account:
            return
        if currency and currency != self.currency:
            return
        parsed = _float_or_none(value)
        if parsed is not None:
            self.summary[tag] = parsed

    def accountSummaryEnd(self, reqId: int) -> None:  # noqa: N802
        self.summary_ready.set()

    def pnl(  # noqa: N802
        self,
        reqId: int,
        dailyPnL: float,
        unrealizedPnL: float,
        realizedPnL: float,
    ) -> None:
        self.pnl_values = {
            "daily_pnl": float(dailyPnL),
            "unrealized_pnl": float(unrealizedPnL),
            "realized_pnl": float(realizedPnL),
        }
        self.pnl_ready.set()

    def updatePortfolio(  # noqa: N802
        self,
        contract: Contract,
        position: float,
        marketPrice: float,
        marketValue: float,
        averageCost: float,
        unrealizedPNL: float,
        realizedPNL: float,
        accountName: str,
    ) -> None:
        if self.account and accountName != self.account:
            return
        symbol = contract.symbol or f"conid-{contract.conId}"
        if position == 0:
            self.portfolio_values.pop(symbol, None)
            return
        self.portfolio_values[symbol] = {
            "position": float(position),
            "market_price": float(marketPrice),
            "market_value": float(marketValue),
            "average_cost": float(averageCost),
            "unrealized_pnl": float(unrealizedPNL),
            "realized_pnl": float(realizedPNL),
        }
        self.portfolio_ready.set()

    def error(self, reqId: int, *args: object) -> None:
        if any("connection is OK" in str(item) for item in args):
            return
        self.errors.append(f"request={reqId}, details={args}")

    def run_loop(self) -> None:
        try:
            self.run()
        except TypeError as exc:
            if "serverVersion" in str(exc) or "NoneType" in str(exc):
                self.errors.append(f"TWS P&L thread stopped during disconnect: {exc}")
                return
            raise

    def sample(self) -> PnlSample:
        account = self.account or (self.accounts[0] if self.accounts else "")
        portfolio_unrealized = _sum_available(
            item.get("unrealized_pnl")
            for item in self.portfolio_values.values()
        )
        portfolio_realized = _sum_available(
            item.get("realized_pnl")
            for item in self.portfolio_values.values()
        )
        return PnlSample(
            timestamp=datetime.now(timezone.utc).isoformat(),
            account=account,
            currency=self.currency,
            daily_pnl=self.pnl_values.get("daily_pnl"),
            unrealized_pnl=_first_not_none(
                portfolio_unrealized,
                self.pnl_values.get("unrealized_pnl"),
                self.summary.get("UnrealizedPnL"),
            ),
            realized_pnl=_first_not_none(
                portfolio_realized,
                self.pnl_values.get("realized_pnl"),
                self.summary.get("RealizedPnL"),
            ),
            net_liquidation=self.summary.get("NetLiquidation"),
            total_cash_value=self.summary.get("TotalCashValue"),
            available_funds=self.summary.get("AvailableFunds"),
            excess_liquidity=self.summary.get("ExcessLiquidity"),
            maintenance_margin=self.summary.get("MaintMarginReq"),
            buying_power=self.summary.get("BuyingPower"),
            gross_position_value=self.summary.get("GrossPositionValue"),
            portfolio_unrealized_pnl=portfolio_unrealized,
            portfolio_realized_pnl=portfolio_realized,
            open_positions=len(self.portfolio_values),
            source="ibkr_readonly_pnl",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=150)
    parser.add_argument("--account", default="")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--csv-output", type=Path, default=PROJECT_ROOT / "reports" / "pnl_timeseries.csv")
    parser.add_argument("--jsonl-output", type=Path, default=PROJECT_ROOT / "reports" / "pnl_timeseries.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")

    settings = Settings.load()
    client = AccountPnlClient(args.account.strip(), args.currency.strip().upper() or "EUR")
    host = args.host or settings.tws_host
    port = args.port or settings.tws_port

    try:
        client.connect(host, port, clientId=args.client_id)
        threading.Thread(target=client.run_loop, daemon=True).start()
        if not client.ready.wait(args.timeout):
            raise RuntimeError("TWS API handshake timed out")

        account = args.account.strip()
        if not account:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline and not client.accounts:
                time.sleep(0.05)
            if client.accounts:
                account = client.accounts[0]
                client.account = account
        if not account:
            raise RuntimeError("No managed account returned by TWS")

        client.reqAccountSummary(9101, "All", SUMMARY_TAGS)
        client.reqPnL(9201, account, "")
        client.reqAccountUpdates(True, account)

        rows = []
        for index in range(args.samples):
            client.summary_ready.wait(args.timeout)
            client.pnl_ready.wait(args.timeout)
            client.portfolio_ready.wait(args.timeout)
            sample = client.sample()
            rows.append(sample)
            append_outputs(args.csv_output, args.jsonl_output, sample)
            print(json.dumps(sample.as_dict(), ensure_ascii=False, sort_keys=True))
            if index < args.samples - 1:
                time.sleep(args.interval_seconds)
        return 0
    finally:
        try:
            client.cancelPnL(9201)
        except Exception:
            pass
        try:
            client.reqAccountUpdates(False, client.account)
        except Exception:
            pass
        try:
            client.cancelAccountSummary(9101)
        except Exception:
            pass
        if client.isConnected():
            client.disconnect()


def append_outputs(csv_output: Path, jsonl_output: Path, sample: PnlSample) -> None:
    payload = sample.as_dict()
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    jsonl_output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(payload)
    existing_rows: List[Dict[str, object]] = []
    write_header = True
    if csv_output.exists():
        with csv_output.open(newline="", encoding="utf-8") as existing:
            reader = csv.DictReader(existing)
            existing_fieldnames = list(reader.fieldnames or [])
            existing_rows = [dict(row) for row in reader]
        if existing_fieldnames == fieldnames:
            write_header = False
        else:
            for name in existing_fieldnames:
                if name and name not in fieldnames:
                    fieldnames.append(name)
            for row in existing_rows:
                row.pop(None, None)
                for name in fieldnames:
                    row.setdefault(name, "")
    with csv_output.open("a", newline="", encoding="utf-8") as handle:
        if write_header and existing_rows:
            handle.seek(0)
            handle.truncate()
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
            for row in existing_rows:
                writer.writerow(row)
        writer.writerow(payload)
    with jsonl_output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _float_or_none(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_not_none(*values: Optional[float]) -> Optional[float]:
    for value in values:
        if value is not None:
            return value
    return None


def _sum_available(values: object) -> Optional[float]:
    total = 0.0
    found = False
    for value in values:
        if value is None:
            continue
        found = True
        total += float(value)
    return total if found else None


if __name__ == "__main__":
    raise SystemExit(main())
