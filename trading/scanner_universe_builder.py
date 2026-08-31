"""Build scanner candidates for the discovery universe."""

from trading.auto_open_pipeline import PipelineConfig, run_ibkr_scanner


def build_scanner_universe(discovery_run_id: str = "manual-scanner-universe") -> dict:
    return run_ibkr_scanner(discovery_run_id, PipelineConfig.from_env())
