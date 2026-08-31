#!/usr/bin/env python3
"""Build report-only status for strategy extensions not allowed to trade yet."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings


REPORT_DIR = PROJECT_ROOT / "reports" / "strategy_extensions"


def build_status(settings: Settings, agent_latest: dict[str, Any] | None = None) -> dict[str, Any]:
    agent_latest = agent_latest or latest_agent_report()
    streaming_enabled = bool(agent_latest.get("streaming_enabled", settings.streaming_market_data_enabled))
    streaming_symbols = list(agent_latest.get("streaming_symbols") or settings.streaming_symbols)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "strategy_extension_status",
        "paper_only": settings.trading_mode == "PAPER",
        "live_enabled": settings.trading_mode not in {"PAPER", "DRY_RUN"},
        "buy_freeze": _bool_env("MODE9_BUY_FREEZE", True),
        "modules": {
            "commission_aware_filter": {
                "status": "roadmap",
                "trade_effect": "none",
                "report_only": True,
                "required_fields": [
                    "ibkr_commission_model",
                    "estimated_buy_commission",
                    "estimated_sell_commission",
                    "round_trip_commission",
                    "expected_gross_profit",
                    "expected_net_profit_after_commission",
                    "reject_buy_when_expected_net_profit_lte_zero",
                ],
                "next_step": "Add dry-run calculations to BUY candidate reports, then gate BUY only after pytest and paper evidence.",
            },
            "market_regime": {
                "status": "roadmap",
                "trade_effect": "none",
                "report_only": True,
                "required_fields": [
                    "spy_trend",
                    "qqq_trend",
                    "regime",
                    "buy_limit_recommendation_for_bearish_or_dangerous_regime",
                ],
                "next_step": "Create SPY/QQQ read-only trend report and keep it advisory until validated.",
            },
            "full_universe_streaming": {
                "status": "available_but_not_strategy_input" if streaming_enabled else "disabled",
                "trade_effect": "none",
                "report_only": True,
                "streaming_enabled": streaming_enabled,
                "streaming_symbols": streaming_symbols,
                "streaming_quote_count": int(agent_latest.get("streaming_quote_count") or 0),
                "streaming_max_symbols": settings.streaming_max_symbols,
                "strategy_input_enabled": False,
                "next_step": "Keep streaming read-only until freshness, coverage, and fallback behavior are validated.",
            },
            "sell_strategy": {
                "status": "roadmap",
                "trade_effect": "protective_sell_stp_only",
                "report_only": True,
                "implemented_now": ["position_protection_repair"],
                "not_enabled": [
                    "take_profit",
                    "trailing_stop",
                    "average_cost_aware_exit",
                    "market_regime_aware_exit",
                    "independent_sell_strategy",
                ],
                "next_step": "Design exits as dry-run proposals before any autonomous SELL strategy beyond protection repair.",
            },
        },
    }


def latest_agent_report() -> dict[str, Any]:
    path = PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_reports(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "status_latest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# Strategy Extension Status",
        "",
        f"- timestamp: {payload['timestamp']}",
        f"- paper_only: {payload['paper_only']}",
        f"- live_enabled: {payload['live_enabled']}",
        f"- buy_freeze: {payload['buy_freeze']}",
        "",
        "| Module | Status | Trade Effect | Report Only | Next Step |",
        "|---|---|---|---|---|",
    ]
    for name, module in payload["modules"].items():
        lines.append(
            f"| {name} | {module['status']} | {module['trade_effect']} | "
            f"{str(module['report_only']).lower()} | {module['next_step']} |"
        )
    (REPORT_DIR / "status_latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bool_env(name: str, default: bool) -> bool:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    payload = build_status(Settings.load())
    write_reports(payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
