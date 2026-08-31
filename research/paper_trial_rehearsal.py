import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.guarded_paper_trial_session import GuardedPaperTrialSessionConfig, run_guarded_session
from trading.config import Settings
from trading.market_data import Quote


READY_HEALTH = {
    "lock_state": "TRADE_LOCK",
    "paper_transmit_enabled": True,
    "kill_switch_enabled": False,
    "tws": {
        "ready_for_orders": True,
        "paper_account": "DU-SIMULATED",
        "error": "",
    },
}


@dataclass(frozen=True)
class PaperTrialRehearsalReport:
    source: str
    created_at: str
    mode: str
    status: str
    guarded_session_status: str
    ibkr_market_data_used: bool
    trading_api_validate_used: bool
    paper_order_used: bool
    artifacts: dict[str, str]


class RehearsalQuoteSource:
    def __init__(self) -> None:
        self.last_errors: list[str] = []
        self.calls = 0
        self.values = [100.0, 102.0, 98.0, 101.5, 98.5, 101.0, 99.0, 100.8, 99.2, 97.5]

    def get_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        price = self.values[self.calls % len(self.values)]
        self.calls += 1
        return [
            Quote(
                symbol=symbol,
                last=price,
                bid=price - 0.01,
                ask=price + 0.01,
                timestamp=datetime.now(timezone.utc),
                source="simulated_rehearsal",
                volume=1000,
            )
            for symbol in symbols
        ]


def run_rehearsal(symbols: Sequence[str], *, output_dir: Path) -> PaperTrialRehearsalReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = _rehearsal_settings(output_dir)
    guarded = run_guarded_session(
        RehearsalQuoteSource(),
        settings,
        health=READY_HEALTH,
        api_error="",
        config=GuardedPaperTrialSessionConfig(
            symbols=symbols,
            samples=20,
            interval_seconds=0.0,
            quotes_csv=output_dir / "quotes.csv",
            recorder_report=output_dir / "ibkr_quote_recorder.json",
            diagnostics_report=output_dir / "mean_reversion_diagnostics.json",
            paper_plan_report=output_dir / "paper_validation_plan.json",
            ibkr_pipeline_report=output_dir / "ibkr_mean_reversion_pipeline.json",
            readiness_report=output_dir / "paper_readiness_report.json",
            execution_gate_report=output_dir / "paper_execution_gate.json",
            full_pipeline_report=output_dir / "full_paper_trial_pipeline.json",
            environment_audit_report=output_dir / "paper_environment_audit.json",
            guarded_session_report=output_dir / "guarded_paper_trial_session.json",
            z_window=10,
            entry_z=0.1,
            submit_validate=False,
            execute_paper=False,
            api_key="",
        ),
    )
    report = PaperTrialRehearsalReport(
        source="paper_trial_rehearsal",
        created_at=datetime.now(timezone.utc).isoformat(),
        mode="simulated_rehearsal",
        status="completed",
        guarded_session_status=guarded.status,
        ibkr_market_data_used=False,
        trading_api_validate_used=False,
        paper_order_used=False,
        artifacts={
            "output_dir": str(output_dir),
            "guarded_session": str(output_dir / "guarded_paper_trial_session.json"),
            "quotes_csv": str(output_dir / "quotes.csv"),
            "paper_plan": str(output_dir / "paper_validation_plan.json"),
            "readiness": str(output_dir / "paper_readiness_report.json"),
            "execution_gate": str(output_dir / "paper_execution_gate.json"),
        },
    )
    (output_dir / "paper_trial_rehearsal.json").write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a simulated ready-environment rehearsal of the guarded paper-trial workflow. No IBKR market data, API validation, or orders."
    )
    parser.add_argument("--symbols", default="AAPL")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_rehearsal")
    args = parser.parse_args()

    report = run_rehearsal(
        [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
        output_dir=args.output_dir,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _rehearsal_settings(output_dir: Path) -> Settings:
    return Settings(
        api_key="rehearsal-key",
        api_host="127.0.0.1",
        api_port=8787,
        trading_mode="PAPER",
        allow_tws_staging=True,
        allow_paper_transmit=True,
        allow_outside_rth=False,
        trading_kill_switch=False,
        trade_session_token="rehearsal-token",
        tws_host="127.0.0.1",
        tws_port=7497,
        tws_client_id=22,
        tws_status_timeout=0.01,
        allowed_symbols=frozenset({"AAPL", "MSFT", "SPY"}),
        max_quantity=1,
        max_order_value=200.0,
        max_risk_per_order=10.0,
        max_daily_notional_value=None,
        daily_notional_timezone="Europe/Berlin",
        streaming_market_data_enabled=False,
        streaming_symbols=("AAPL", "MSFT", "NVDA"),
        streaming_max_symbols=3,
        streaming_stale_ms=3000.0,
        streaming_tws_host="127.0.0.1",
        streaming_tws_port=7497,
        streaming_client_id=32,
        audit_db=output_dir / "audit.sqlite3",
    )


if __name__ == "__main__":
    raise SystemExit(main())
