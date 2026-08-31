"""Local simulated order executor."""

from trading.auto_open_pipeline import PipelineConfig, run_auto_open_pipeline, run_local_simulation


def run(discovery_run_id: str = "manual-simulation") -> dict:
    result = run_auto_open_pipeline("simulation-debug", config=PipelineConfig.from_env())
    return result["simulation"]
