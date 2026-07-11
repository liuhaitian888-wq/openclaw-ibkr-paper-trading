"""Unified discovery orchestrator entrypoint."""

from trading.auto_open_pipeline import PipelineConfig, run_discovery_orchestrator


def run(discovery_run_id: str = "manual-discovery") -> dict:
    return run_discovery_orchestrator(discovery_run_id, PipelineConfig.from_env())
