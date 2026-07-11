"""Future paper execution gate. Report-only and default false."""

from trading.auto_open_pipeline import PipelineConfig, run_paper_execution_gate


def run(cycle_id: str = "manual-paper-gate") -> dict:
    return run_paper_execution_gate(cycle_id, PipelineConfig.from_env(), {"mode": "LOCAL_SIMULATION_ONLY"})
