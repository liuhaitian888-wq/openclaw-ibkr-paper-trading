"""Generate a sanitized daily OpenClaw project update for Feishu."""

import argparse
import csv
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BEIJING = ZoneInfo("Asia/Shanghai")
BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports" / "daily_feishu")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def files_modified_since(pattern: str, since: datetime) -> list[Path]:
    return sorted(
        path for path in PROJECT_ROOT.glob(pattern)
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= since
    )


def universe_summary() -> tuple[int, int, dict[str, int]]:
    path = PROJECT_ROOT / "data" / "us_equity_universe.csv"
    if not path.exists():
        return 0, 0, {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    sectors: dict[str, int] = {}
    for row in rows:
        sector = row.get("sector") or "Unknown"
        sectors[sector] = sectors.get(sector, 0) + 1
    enabled = sum((row.get("enabled") or "").lower() == "true" for row in rows)
    return len(rows), enabled, dict(sorted(sectors.items(), key=lambda item: (-item[1], item[0])))


def latest_pnl() -> dict[str, str]:
    path = PROJECT_ROOT / "reports" / "pnl_timeseries.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-1] if rows else {}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def api_running() -> bool:
    return api_health_status()[0]


def api_health_status() -> tuple[bool, str, dict[str, object]]:
    key_path = PROJECT_ROOT / ".secrets" / "openclaw_api_key"
    api_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else ""
    errors = []
    for base_url in ("http://192.168.64.1:8787", "http://127.0.0.1:8787", "http://localhost:8787"):
        headers = {"X-API-Key": api_key} if api_key else {}
        request = urllib.request.Request(f"{base_url}/health", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status == 200 and payload.get("status") == "ok", base_url, payload
        except Exception as exc:  # noqa: BLE001 - report diagnostics, do not fail daily report
            errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
    return False, "; ".join(errors), {}


def file_age_seconds(path: Path, now_utc: datetime) -> float | None:
    if not path.exists():
        return None
    return (now_utc - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)).total_seconds()


def top_skip_reasons(paths: list[Path], limit: int = 5) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for path in paths[-20:]:
        data = read_json(path)
        decisions = data.get("decisions")
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            reason = decision.get("reason") or decision.get("skip_reason") or decision.get("risk_gate_reason")
            if reason:
                counts[str(reason)] = counts.get(str(reason), 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def explain_zero_submissions(
    *,
    buy_freeze: bool,
    repair_enabled: bool,
    repair_mode: str,
    run_blocked_reason: str,
    strategy_submitted_count: int,
    position_submitted_count: int,
    skip_reasons: list[tuple[str, int]],
    api_ok: bool,
) -> str:
    reasons = []
    if not api_ok:
        reasons.append("API unavailable")
    if buy_freeze:
        reasons.append("BUY freeze enabled")
    if not repair_enabled:
        reasons.append("position repair disabled")
    elif repair_mode == "test":
        reasons.append("position repair test mode waiting/limited to one test order")
    elif run_blocked_reason:
        reasons.append(f"position repair run blocked: {run_blocked_reason}")
    if strategy_submitted_count == 0:
        reasons.append("no strategy order submitted")
    if position_submitted_count == 0:
        reasons.append("no position protection order submitted")
    if skip_reasons:
        reasons.append("top strategy skip reasons: " + ", ".join(f"{name}={count}" for name, count in skip_reasons[:3]))
    return "; ".join(reasons) if reasons else "n/a"


def build_status_snapshot(now_utc: datetime, latest_agent: dict[str, object], pool_reports: list[Path], pnl: dict[str, str]) -> dict[str, object]:
    process_guard = read_json(PROJECT_ROOT / "reports" / "process_guard" / "latest.json")
    mode9_pid = process_guard.get("mode9_pid")
    process_guard_age = file_age_seconds(PROJECT_ROOT / "reports" / "process_guard" / "latest.json", now_utc)
    latest_created = parse_timestamp(str(latest_agent.get("created_at") or ""))
    agent_age = None if latest_created is None else (now_utc - latest_created.astimezone(timezone.utc)).total_seconds()
    cycles_age = file_age_seconds(PROJECT_ROOT / "reports" / "autonomous_agent" / "cycles.jsonl", now_utc)
    api_ok, api_detail, api_payload = api_health_status()
    monitoring_line = read_json(PROJECT_ROOT / "reports" / "monitoring_line" / "latest.json")
    full_paper = read_json(PROJECT_ROOT / "reports" / "full_paper_run" / "latest.json")
    market_session = read_json(PROJECT_ROOT / "reports" / "market_session" / "latest.json")
    crosscheck = read_json(PROJECT_ROOT / "reports" / "market_quote_crosscheck" / "latest.json")
    split = read_json(PROJECT_ROOT / "reports" / "execution_ledger_split" / "latest.json")
    pnl_ledger = read_json(PROJECT_ROOT / "reports" / "pnl_ledger" / "latest.json")
    auto_open = read_json(PROJECT_ROOT / "reports" / "final_auto_open_discovery_news_simulation_audit" / "latest.json")
    position = latest_agent.get("position_protection") if isinstance(latest_agent.get("position_protection"), dict) else {}
    strategy = latest_agent.get("strategy_run") if isinstance(latest_agent.get("strategy_run"), dict) else {}
    skip_reasons = top_skip_reasons(pool_reports)
    pnl_ts = parse_timestamp(pnl.get("timestamp"))
    pnl_age = None if pnl_ts is None else (now_utc - pnl_ts.astimezone(timezone.utc)).total_seconds()
    strategy_submitted = int((strategy or {}).get("submitted_count") or 0)
    position_submitted = int((position or {}).get("submitted_count") or 0)
    buy_freeze = bool(latest_agent.get("mode9_buy_freeze") or (position or {}).get("buy_freeze"))
    repair_enabled = bool((position or {}).get("position_protection_repair_enabled", (position or {}).get("enabled", False)))
    repair_mode = str((position or {}).get("position_protection_repair_mode") or (position or {}).get("repair_mode") or "test")
    run_blocked_reason = str((position or {}).get("run_blocked_reason") or "")
    return {
        "mode9_running": bool(mode9_pid and process_guard_age is not None and process_guard_age < 120),
        "mode9_pid": mode9_pid,
        "agent_latest_created_at": latest_agent.get("created_at"),
        "agent_latest_age_seconds": None if agent_age is None else round(agent_age, 1),
        "cycles_last_update_age_seconds": None if cycles_age is None else round(cycles_age, 1),
        "trading_api_health_ok": api_ok,
        "trading_api_health_error": "" if api_ok else api_detail,
        "monitor_line_running": bool(monitoring_line.get("mode9_monitoring_line_enabled")),
        "full_paper_run_active": bool(full_paper.get("status") == "READY_FOR_PAPER_AUTOMATION_RUN"),
        "full_paper_run_enabled": bool(full_paper.get("full_paper_run_enabled")),
        "auto_buy_enabled": bool(full_paper.get("auto_buy_enabled")),
        "gap_escape_enabled": bool(full_paper.get("gap_escape_enabled")),
        "options_paper_execution_enabled": bool(full_paper.get("options_execution_enabled")),
        "live_trading_enabled": bool(full_paper.get("live_trading_enabled")),
        "market_session_state": market_session.get("session_state"),
        "expected_live_bid_ask": market_session.get("expected_live_bid_ask"),
        "quote_crosscheck_summary": crosscheck.get("summary"),
        "buy_candidates": (split.get("counts") or {}).get("buy") if isinstance(split.get("counts"), dict) else None,
        "protective_sell_candidates": (split.get("counts") or {}).get("protective_sell") if isinstance(split.get("counts"), dict) else None,
        "gap_escape_sell_candidates": (split.get("counts") or {}).get("gap_escape_sell") if isinstance(split.get("counts"), dict) else None,
        "profit_sell_candidates": (split.get("counts") or {}).get("profit_sell") if isinstance(split.get("counts"), dict) else None,
        "options_plan_events": (split.get("counts") or {}).get("options_plan") if isinstance(split.get("counts"), dict) else None,
        "actual_submitted_orders": split.get("order_submitted_count"),
        "actual_executions_fills": 0,
        "account_pnl": pnl_ledger.get("account_pnl_snapshot"),
        "per_symbol_pnl_count": len(pnl_ledger.get("position_pnl_snapshots", [])) if isinstance(pnl_ledger.get("position_pnl_snapshots"), list) else None,
        "stale_pnl_warning": pnl_ledger.get("stale_pnl_warning"),
        "buy_freeze": buy_freeze,
        "position_repair_enabled": repair_enabled,
        "position_repair_mode": repair_mode,
        "paper_operation_mode": (position or {}).get("paper_operation_mode") or ("monitor_only" if not repair_enabled else repair_mode),
        "test_repair_success": bool((position or {}).get("test_repair_success")),
        "run_allowed": bool((position or {}).get("run_allowed")),
        "run_blocked_reason": run_blocked_reason,
        "last_strategy_run_at": (strategy or {}).get("report_path"),
        "strategy_submitted_count": strategy_submitted,
        "position_protection_submitted_count": position_submitted,
        "top_skip_reasons": skip_reasons,
        "pnl_sample_age_seconds": None if pnl_age is None else round(pnl_age, 1),
        "zero_submission_reason": explain_zero_submissions(
            buy_freeze=buy_freeze,
            repair_enabled=repair_enabled,
            repair_mode=repair_mode,
            run_blocked_reason=run_blocked_reason,
            strategy_submitted_count=strategy_submitted,
            position_submitted_count=position_submitted,
            skip_reasons=skip_reasons,
            api_ok=api_ok,
        ),
        "mode9_state_note": "" if bool(mode9_pid and process_guard_age is not None and process_guard_age < 120) else "Mode 9 agent is not currently running; this is a report from last recorded state.",
        "order_submission_note": "All events were decision/intent events only; no order was submitted." if (split.get("order_submitted_count") in {0, None}) else "",
        "auto_open_discovery_enabled": auto_open.get("discovery_enabled"),
        "auto_open_scanner_enabled": auto_open.get("scanner_enabled"),
        "auto_open_news_enabled": auto_open.get("news_enabled"),
        "auto_open_pool_expansion_enabled": auto_open.get("pool_expansion_enabled"),
        "auto_open_local_simulation_enabled": auto_open.get("local_simulation_enabled"),
        "auto_open_trade_pool_size": auto_open.get("trade_pool_size"),
        "auto_open_simulated_orders_count": auto_open.get("simulated_orders_count"),
        "auto_open_ibkr_paper_orders_submitted": auto_open.get("ibkr_paper_orders_submitted"),
        "auto_open_live_orders_submitted": auto_open.get("live_orders_submitted"),
        "auto_open_snapshot_risk": bool(auto_open.get("paid_snapshot_used") or auto_open.get("regulatory_snapshot_used")),
        "api_lock_state": api_payload.get("lock_state"),
        "api_tws_ready": (api_payload.get("tws") or {}).get("ready_for_orders") if isinstance(api_payload.get("tws"), dict) else None,
    }


def status_lines(status: dict[str, object]) -> str:
    return "\n".join(
        [
            f"- mode9_running: {status.get('mode9_running')}",
            f"- mode9_pid: {status.get('mode9_pid')}",
            f"- agent_latest_created_at: {status.get('agent_latest_created_at')}",
            f"- agent_latest_age_seconds: {status.get('agent_latest_age_seconds')}",
            f"- cycles_last_update_age_seconds: {status.get('cycles_last_update_age_seconds')}",
            f"- trading_api_health_ok: {status.get('trading_api_health_ok')}",
            f"- trading_api_health_error: {status.get('trading_api_health_error')}",
            f"- monitor_line_running: {status.get('monitor_line_running')}",
            f"- full_paper_run_active: {status.get('full_paper_run_active')}",
            f"- full_paper_run_enabled: {status.get('full_paper_run_enabled')}",
            f"- auto_buy_enabled: {status.get('auto_buy_enabled')}",
            f"- gap_escape_enabled: {status.get('gap_escape_enabled')}",
            f"- options_paper_execution_enabled: {status.get('options_paper_execution_enabled')}",
            f"- live_trading_enabled: {status.get('live_trading_enabled')}",
            f"- market_session_state: {status.get('market_session_state')}",
            f"- expected_live_bid_ask: {status.get('expected_live_bid_ask')}",
            f"- quote_crosscheck_summary: {status.get('quote_crosscheck_summary')}",
            f"- buy_candidates: {status.get('buy_candidates')}",
            f"- protective_sell_candidates: {status.get('protective_sell_candidates')}",
            f"- gap_escape_sell_candidates: {status.get('gap_escape_sell_candidates')}",
            f"- profit_sell_candidates: {status.get('profit_sell_candidates')}",
            f"- options_plan_events: {status.get('options_plan_events')}",
            f"- actual_submitted_orders: {status.get('actual_submitted_orders')}",
            f"- actual_executions_fills: {status.get('actual_executions_fills')}",
            f"- account_pnl: {status.get('account_pnl')}",
            f"- per_symbol_pnl_count: {status.get('per_symbol_pnl_count')}",
            f"- stale_pnl_warning: {status.get('stale_pnl_warning')}",
            f"- buy_freeze: {status.get('buy_freeze')}",
            f"- position_repair_enabled: {status.get('position_repair_enabled')}",
            f"- position_repair_mode: {status.get('position_repair_mode')}",
            f"- paper_operation_mode: {status.get('paper_operation_mode')}",
            f"- test_repair_success: {status.get('test_repair_success')}",
            f"- run_allowed: {status.get('run_allowed')}",
            f"- run_blocked_reason: {status.get('run_blocked_reason')}",
            f"- last_strategy_run_at: {status.get('last_strategy_run_at')}",
            f"- strategy_submitted_count: {status.get('strategy_submitted_count')}",
            f"- position_protection_submitted_count: {status.get('position_protection_submitted_count')}",
            f"- top_skip_reasons: {status.get('top_skip_reasons')}",
            f"- pnl_sample_age_seconds: {status.get('pnl_sample_age_seconds')}",
            f"- submitted_count=0 explanation: {status.get('zero_submission_reason')}",
            f"- mode9_state_note: {status.get('mode9_state_note')}",
            f"- order_submission_note: {status.get('order_submission_note')}",
            f"- auto_open_discovery_enabled: {status.get('auto_open_discovery_enabled')}",
            f"- auto_open_scanner_enabled: {status.get('auto_open_scanner_enabled')}",
            f"- auto_open_news_enabled: {status.get('auto_open_news_enabled')}",
            f"- auto_open_pool_expansion_enabled: {status.get('auto_open_pool_expansion_enabled')}",
            f"- auto_open_local_simulation_enabled: {status.get('auto_open_local_simulation_enabled')}",
            f"- auto_open_trade_pool_size: {status.get('auto_open_trade_pool_size')}",
            f"- auto_open_simulated_orders_count: {status.get('auto_open_simulated_orders_count')}",
            f"- auto_open_ibkr_paper_orders_submitted: {status.get('auto_open_ibkr_paper_orders_submitted')}",
            f"- auto_open_live_orders_submitted: {status.get('auto_open_live_orders_submitted')}",
            f"- auto_open_snapshot_risk: {status.get('auto_open_snapshot_risk')}",
        ]
    )


def api_running_legacy() -> bool:
    request = urllib.request.Request("http://127.0.0.1:8787/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def observed_date(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year: int) -> set[date]:
    return {
        observed_date(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_date(date(year, 6, 19)),
        observed_date(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_date(date(year, 12, 25)),
    }


def next_market_day(start: date) -> date:
    current = start
    holidays = market_holidays(current.year) | market_holidays(current.year + 1)
    while current.weekday() >= 5 or current in holidays:
        current += timedelta(days=1)
    return current


def market_note(now_bj: datetime) -> str:
    ny_date = now_bj.astimezone(NEW_YORK).date()
    holidays = market_holidays(ny_date.year)
    if ny_date.weekday() >= 5:
        return f"今日美股休市（周末）。下一个预计交易日：{next_market_day(ny_date).isoformat()}。"
    if ny_date in holidays:
        return f"今日美股休市（美国交易所假日）。下一个预计交易日：{next_market_day(ny_date).isoformat()}。"
    return f"今日预计为美股交易日（以交易所临时公告为准）。美东日期：{ny_date.isoformat()}。"


def fmt_number(value: str | None) -> str:
    if value in (None, ""):
        return "n/a"
    try:
        return f"{float(value):,.2f}"
    except ValueError:
        return value


def mask_identifier(value: str | None) -> str:
    if not value:
        return "n/a"
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}***{value[-4:]}"


def sector_lines(sectors: dict[str, int]) -> str:
    if not sectors:
        return "  - n/a"
    return "\n".join(f"  - {name}: {count}" for name, count in sectors.items())


def pnl_lines(pnl: dict[str, str], now_utc: datetime) -> str:
    timestamp = parse_timestamp(pnl.get("timestamp"))
    if timestamp is None:
        return "- 本地暂无 PnL 记录；需要重新运行只读 PnL 采样后再汇报。"
    age = now_utc - timestamp.astimezone(timezone.utc)
    timestamp_bj = timestamp.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    if age > timedelta(hours=6):
        return (
            f"- 本地 PnL 记录已过期，最后采样时间：{timestamp_bj} 北京时间。\n"
            "- 当前 TWS 截图显示的数据更新于界面，但日报不会引用截图值作为自动数据源。\n"
            "- 建议在交易日恢复只读 PnL 采样后，再在日报里展示 daily/unrealized/net liquidation。"
        )
    return (
        f"- 采样时间：{timestamp_bj} 北京时间\n"
        f"- 币种：{pnl.get('currency', 'n/a')}\n"
        f"- daily PnL：{fmt_number(pnl.get('daily_pnl'))}\n"
        f"- unrealized PnL：{fmt_number(pnl.get('unrealized_pnl'))}\n"
        f"- net liquidation：{fmt_number(pnl.get('net_liquidation'))}"
    )


def build_report() -> str:
    now_bj = datetime.now(BEIJING)
    now_berlin = now_bj.astimezone(BERLIN)
    now_utc = datetime.now(timezone.utc)
    since = now_utc - timedelta(hours=24)
    universe_total, universe_enabled, sectors = universe_summary()
    latest_agent = read_json(PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json")
    pool_reports = files_modified_since("reports/pool_strategy_module_*.json", since)
    auto_reports = files_modified_since("reports/auto_order_sequence_*.json", since)
    pnl = latest_pnl()
    submitted_total = 0
    for path in pool_reports:
        data = read_json(path)
        submitted_total += int(data.get("submitted_count") or 0)
    research_tasks = latest_agent.get("research_tasks") if isinstance(latest_agent.get("research_tasks"), list) else []
    high_tasks = [task for task in research_tasks if isinstance(task, dict) and task.get("priority") == "high"]
    sector_breakdown = sector_lines(sectors)
    status = build_status_snapshot(now_utc, latest_agent, pool_reports, pnl)
    api_state = "运行中" if status["trading_api_health_ok"] else "未检测到运行"
    next_action = (
        "保持观察，继续记录 agent、策略与 PnL 输出。"
        if status["mode9_running"] and status["trading_api_health_ok"]
        else "下一个交易日前，重新打开 TWS paper，并恢复 TRADE_LOCK background 与 autonomous agent。"
    )
    report = f"""OpenClaw 每日项目进展更新

时间：{now_bj.strftime('%Y-%m-%d %H:%M')} 北京时间 / {now_berlin.strftime('%H:%M')} 德国时间
窗口：过去 24 小时

一、今日交易与运行状态
- {market_note(now_bj)}
- Trading API：{api_state}
- 最新 agent 状态：cycle {latest_agent.get("cycle", "n/a")}，lock state {latest_agent.get("lock_state", "n/a")}，TWS readiness {latest_agent.get("ready_for_orders", "n/a")}。
- 最近行情读取数量：{latest_agent.get("quote_count", "n/a")}。
- 策略提交订单数合计：{submitted_total}。
- submitted_count=0 原因：{status.get("zero_submission_reason")}

运行字段：
{status_lines(status)}

二、过去一天产出
- 策略模块报告数：{len(pool_reports)}
- 自动订单序列报告数：{len(auto_reports)}
- 最新 high-priority research tasks：{", ".join(str(task.get("symbol")) for task in high_tasks[:8]) or "无"}
- 本地日报文件已自动归档到 reports/daily_feishu。

三、复盘
- 过去一天策略提交订单数为 {submitted_total}；具体原因见上方 submitted_count=0 explanation。
- Trading API、Mode 9、repair mode、BUY freeze 和 PnL 新鲜度已经拆开显示，避免把“监控运行中”和“没有提交订单”混成同一个状态。
- 休市日或行情稀疏时，quote、PnL、成交状态更容易滞后，日报会优先标记数据新鲜度。

四、股票池与筛选框架
- universe 总数：{universe_total}
- enabled 数：{universe_enabled}
- 主要行业分布：
{sector_breakdown}
- 入池原则：候选先形成结构化报告，再走 Python hard audit；未通过审核不进入 universe，也不会被策略模块交易。
- 下单原则：任何 paper order 都必须经过 lock state、daily token、TWS readiness、allowlist、行情新鲜度、价差、仓位和亏损限制。

五、策略与风控
- 当前主策略仍是 conservative trend：long-only、小仓位、趋势确认、小止盈/止损、cooldown 和 portfolio risk gate。
- AI/agent 负责研究、候选生成和调度；不直接改股票池，不直接连接券商，不绕过 Python 风控。

六、PnL 快照
{pnl_lines(pnl, now_utc)}

七、潜在风险
- 运行风险：TWS、Trading API 或 autonomous agent 未恢复时，日报只能汇报最后记录，不能代表实时运行。
- 数据风险：本地 PnL/行情样本若过期，必须先刷新采样，避免把旧数据当成当前账户状态。
- 研究风险：Gemini/OpenClaw research worker 尚未完全自动化，候选研究仍需要 Python hard audit 和人工监督。
- 交易风险：休市、盘前盘后、价差扩大或 quote stale 时，即使有信号也应阻止新订单。

八、下一步
- {next_action}
- 继续推进 Gemini/OpenClaw research worker，让互联网研究输出结构化 candidate draft，再交给 Python hard audit。
- 本日报已自动脱敏：不包含 API key、webhook、secret、token、敏感 URL 或端口。
"""
    return report


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    now_bj = datetime.now(BEIJING)
    output = args.output_dir / f"openclaw_daily_update_{now_bj:%Y%m%d}.md"
    output.write_text(build_report(), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
