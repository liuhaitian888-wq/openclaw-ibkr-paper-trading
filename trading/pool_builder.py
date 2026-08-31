"""Dynamic six-layer pool builder."""

from trading.auto_open_pipeline import PipelineConfig, run_discovery_orchestrator, run_dynamic_pool, run_ibkr_scanner, run_news_pipeline


def run(discovery_run_id: str = "manual-dynamic-pool") -> dict:
    config = PipelineConfig.from_env()
    discovery = run_discovery_orchestrator(discovery_run_id, config)
    scanner = run_ibkr_scanner(discovery_run_id, config)
    news = run_news_pipeline(discovery_run_id, config, discovery, scanner)
    return run_dynamic_pool(discovery_run_id, config, discovery, scanner, news)
