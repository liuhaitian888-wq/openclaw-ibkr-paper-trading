"""Local simulated PnL helpers."""

from trading.auto_open_pipeline import run_auto_open_pipeline


def refresh() -> dict:
    return run_auto_open_pipeline("simulation-pnl")["simulation"]
