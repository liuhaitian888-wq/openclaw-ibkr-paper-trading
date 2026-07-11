import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.config import PROJECT_ROOT, Settings


REPORT_DIR = PROJECT_ROOT / "reports" / "options_hedge"


@dataclass(frozen=True)
class OptionHedgeConfig:
    report_only: bool = True
    paper_only: bool = True
    min_position_notional: float = 30_000.0
    collar_trigger_notional: float = 50_000.0
    force_hedge_review_notional: float = 100_000.0
    protective_put_trigger_notional: float = 30_000.0
    min_shares_per_contract: int = 100
    target_dte_min: int = 21
    target_dte_max: int = 60
    put_otm_pct: float = 0.05
    call_otm_pct: float = 0.08
    max_option_spread_pct: float = 0.15
    min_open_interest: int = 100
    min_volume: int = 10
    max_premium_pct_of_position: float = 0.03


def load_option_hedge_config() -> OptionHedgeConfig:
    return OptionHedgeConfig(
        report_only=_bool_env("OPTION_HEDGE_REPORT_ONLY", True),
        paper_only=_bool_env("OPTION_HEDGE_PAPER_ONLY", True),
        min_position_notional=_float_env("OPTION_HEDGE_MIN_POSITION_NOTIONAL", 30_000.0),
        collar_trigger_notional=_float_env("COLLAR_TRIGGER_NOTIONAL", 50_000.0),
        force_hedge_review_notional=_float_env("FORCE_HEDGE_REVIEW_NOTIONAL", 100_000.0),
        protective_put_trigger_notional=_float_env("PROTECTIVE_PUT_TRIGGER_NOTIONAL", 30_000.0),
        min_shares_per_contract=int(_float_env("OPTION_HEDGE_MIN_SHARES_PER_CONTRACT", 100)),
        target_dte_min=int(_float_env("OPTION_HEDGE_TARGET_DTE_MIN", 21)),
        target_dte_max=int(_float_env("OPTION_HEDGE_TARGET_DTE_MAX", 60)),
        put_otm_pct=_float_env("OPTION_HEDGE_PUT_OTM_PCT", 0.05),
        call_otm_pct=_float_env("OPTION_HEDGE_CALL_OTM_PCT", 0.08),
        max_option_spread_pct=_float_env("OPTION_HEDGE_MAX_OPTION_SPREAD_PCT", 0.15),
        min_open_interest=int(_float_env("OPTION_HEDGE_MIN_OPEN_INTEREST", 100)),
        min_volume=int(_float_env("OPTION_HEDGE_MIN_VOLUME", 10)),
        max_premium_pct_of_position=_float_env("OPTION_HEDGE_MAX_PREMIUM_PCT_OF_POSITION", 0.03),
    )


def build_options_hedge_report(
    *,
    position_guard: Mapping[str, Any],
    event_risk_report: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
    config: OptionHedgeConfig | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.load()
    config = config or load_option_hedge_config()
    event_by_symbol = {str(row.get("symbol", "")).upper(): row for row in (event_risk_report or {}).get("symbols", []) if isinstance(row, Mapping)}
    rows = [
        option_hedge_plan(row, event=event_by_symbol.get(str(row.get("symbol", "")).upper(), {}), config=config, settings=settings)
        for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0
    ]
    report = {
        "timestamp": _now(),
        "source": "options_hedge_planner",
        "config": asdict(config),
        "paper_only": settings.trading_mode == "PAPER",
        "live_enabled": settings.trading_mode not in {"PAPER", "DRY_RUN"},
        "symbols": rows,
        "submitted_count": 0,
        "status": "ok",
    }
    write_report(report)
    return report


def option_hedge_plan(
    position: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
    config: OptionHedgeConfig,
    settings: Settings,
) -> dict[str, Any]:
    symbol = str(position.get("symbol", "")).upper()
    qty = float(position.get("position_qty") or 0)
    price = float(position.get("market_price") or position.get("last") or 0)
    notional = qty * price
    contracts = int(qty // config.min_shares_per_contract)
    event_high = float(event.get("event_risk_score") or 0) >= 0.7
    eligible = notional >= config.min_position_notional and qty >= config.min_shares_per_contract and contracts > 0
    needs_portfolio_hedge = notional >= config.protective_put_trigger_notional and qty < config.min_shares_per_contract
    if not eligible:
        if needs_portfolio_hedge:
            reason = "single_stock_option_hedge_not_available_due_to_small_share_count"
        else:
            reason = "position notional below trigger" if notional < config.min_position_notional else "single_stock_option_hedge_not_available_due_to_small_share_count"
        strategy = "none"
    elif notional >= config.collar_trigger_notional or event_high:
        reason = "eligible for collar planning"
        strategy = "collar"
    else:
        reason = "eligible for protective put planning"
        strategy = "protective_put"
    put_strike = round(price * (1 - config.put_otm_pct), 2) if strategy != "none" else None
    call_strike = round(price * (1 + config.call_otm_pct), 2) if strategy == "collar" else None
    covered_call_safe = strategy != "collar" or contracts <= int(qty // 100)
    naked_option_risk = strategy == "collar" and not covered_call_safe
    estimated_put = round(price * config.put_otm_pct * 0.25, 4) if strategy in {"protective_put", "collar"} else None
    estimated_call = round(price * config.call_otm_pct * 0.20, 4) if strategy == "collar" else None
    estimated_net = None if estimated_put is None else round((estimated_put - (estimated_call or 0.0)) * contracts * 100, 4)
    premium_pct = None if estimated_net is None or notional <= 0 else round(max(0.0, estimated_net) / notional, 6)
    too_expensive = premium_pct is not None and premium_pct > config.max_premium_pct_of_position
    liquidity_available = False
    liquidity_passed = False
    force_review = notional >= config.force_hedge_review_notional
    return {
        "timestamp": _now(),
        "symbol": symbol,
        "position_qty": qty,
        "position_notional": round(notional, 4),
        "eligible_for_options_hedge": eligible,
        "reason": reason,
        "strategy": strategy,
        "contracts": contracts if strategy != "none" else 0,
        "put_strike": put_strike,
        "call_strike": call_strike,
        "expiry": f"{config.target_dte_min}-{config.target_dte_max} DTE",
        "estimated_put_premium": estimated_put,
        "estimated_call_premium": estimated_call,
        "estimated_net_cost": estimated_net,
        "estimated_premium_pct_of_position": premium_pct,
        "max_premium_pct_of_position": config.max_premium_pct_of_position,
        "too_expensive": too_expensive,
        "downside_floor": put_strike,
        "upside_cap": call_strike,
        "max_short_call_contracts": int(qty // 100),
        "covered_call_safe": covered_call_safe,
        "naked_option_risk": naked_option_risk,
        "option_liquidity_data_available": liquidity_available,
        "option_liquidity_passed": liquidity_passed,
        "option_liquidity_reject_reason": "option chain liquidity data missing; require spread/open_interest/volume before execution" if strategy != "none" else "",
        "portfolio_hedge_plan": "consider SPY/QQQ puts instead of single-stock options" if needs_portfolio_hedge else "",
        "force_hedge_review": force_review,
        "action_allowed": False,
        "action_taken": "report_only",
        "paper_only": settings.trading_mode == "PAPER",
        "decision_chain": [
            {"step": "report_only", "value": config.report_only, "effect": "no options orders can be submitted"},
            {"step": "single_stock_share_count", "position_qty": qty, "required": config.min_shares_per_contract, "passed": qty >= config.min_shares_per_contract},
            {"step": "position_notional", "value": round(notional, 4), "protective_put_trigger": config.protective_put_trigger_notional, "collar_trigger": config.collar_trigger_notional, "force_review": config.force_hedge_review_notional},
            {"step": "strategy_selection", "strategy": strategy, "reason": reason},
            {"step": "dte_range", "min": config.target_dte_min, "max": config.target_dte_max},
            {"step": "strike_selection", "put_otm_pct": config.put_otm_pct, "call_otm_pct": config.call_otm_pct, "put_strike": put_strike, "call_strike": call_strike},
            {"step": "collar_covered_call_check", "contracts": contracts if strategy != "none" else 0, "max_short_call_contracts": int(qty // 100), "covered_call_safe": covered_call_safe},
            {"step": "liquidity_check", "required_max_spread_pct": config.max_option_spread_pct, "required_open_interest": config.min_open_interest, "required_volume": config.min_volume, "passed": liquidity_passed, "reason": "missing option chain data"},
            {"step": "premium_check", "estimated_pct": premium_pct, "max_allowed": config.max_premium_pct_of_position, "too_expensive": too_expensive},
            {"step": "action_allowed", "value": False, "reason": "options hedge remains report-only unless explicitly enabled later"},
        ],
    }


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(_markdown(report), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Options Hedge Planner",
        "",
        f"- timestamp: {report.get('timestamp')}",
        f"- submitted_count: {report.get('submitted_count')}",
        "",
        "| Symbol | Eligible | Strategy | Contracts | Reason | Action |",
        "|---|---:|---|---:|---|---|",
    ]
    for row in report.get("symbols", []):
        lines.append(
            f"| {row.get('symbol')} | {row.get('eligible_for_options_hedge')} | "
            f"{row.get('strategy')} | {row.get('contracts')} | {row.get('reason')} | {row.get('action_taken')} |"
        )
    return "\n".join(lines) + "\n"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
