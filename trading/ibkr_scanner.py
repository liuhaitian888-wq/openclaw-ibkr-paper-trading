"""IBKR scanner diagnostics and local discovery fallback."""

from trading.auto_open_pipeline import PipelineConfig, run_ibkr_scanner


def run(discovery_run_id: str = "manual-scanner") -> dict:
    return run_ibkr_scanner(discovery_run_id, PipelineConfig.from_env())
