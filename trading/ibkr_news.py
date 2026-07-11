"""IBKR news interface diagnostics."""

from trading.auto_open_pipeline import PipelineConfig, ibkr_news_interface_tests, news_provider_status


def run_interface_tests(discovery_run_id: str = "manual-ibkr-news") -> dict:
    config = PipelineConfig.from_env()
    providers = news_provider_status(discovery_run_id, config)
    tests = ibkr_news_interface_tests(discovery_run_id, providers)
    return {"discovery_run_id": discovery_run_id, "providers": providers, "interface_tests": tests}
