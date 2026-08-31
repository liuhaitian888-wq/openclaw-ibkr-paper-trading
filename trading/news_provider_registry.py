"""Unified news provider registry for IBKR, RSS, SEC, earnings, cache, and fixtures."""

from trading.auto_open_pipeline import PipelineConfig, news_provider_status


def build_registry(discovery_run_id: str = "manual-news-registry") -> dict:
    config = PipelineConfig.from_env()
    providers = news_provider_status(discovery_run_id, config)
    return {"discovery_run_id": discovery_run_id, "providers": providers}
