"""Deterministic QA renderer for Paper Trading daily diagnostics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TITLE = "买 der · Paper Trading 日报"


@dataclass(frozen=True)
class DailyReportView:
    title: str
    date_utc: str
    status: str
    questions: list[tuple[str, str]]


def build_daily_report_view(report: Mapping[str, Any]) -> DailyReportView:
    snapshot = mapping(report.get("account_snapshot"))
    quality = mapping(report.get("data_quality"))
    runtime = mapping(report.get("runtime"))
    funnel = mapping(report.get("lifecycle_funnel"))
    positions = list_of_mappings(snapshot.get("positions"))
    coverage = list_of_mappings(snapshot.get("protective_order_coverage"))
    market_state = str(runtime.get("market_session_state") or "")
    status = daily_status(report)
    qa = [
        ("今天系统正常吗？", system_answer(status, quality, runtime)),
        ("IBKR/TWS 正常吗？", ibkr_answer(runtime)),
        ("账户现在多少钱？", account_answer(snapshot)),
        ("今天赚了还是亏了？", pnl_answer(snapshot)),
        ("现在有多少仓位？", positions_answer(positions, snapshot)),
        ("这些仓位都有保护吗？", protection_answer(positions, coverage, snapshot)),
        ("实时行情正常吗？", market_data_answer(report, market_state, quality)),
        ("今天策略有动作吗？", strategy_answer(funnel)),
        ("今天下单了吗？", orders_answer(funnel)),
        ("为什么没有下单？", no_order_answer(report, quality, runtime)),
        ("Mode 9 现在运行吗？", mode9_answer(runtime)),
        ("现在 PAPER_READY 吗？", paper_ready_answer(report, quality, runtime, positions, coverage)),
        ("下一步系统要解决什么？", next_steps_answer(report, quality, runtime, positions, coverage)),
    ]
    return DailyReportView(TITLE, str(report.get("trading_date") or report.get("date_utc") or ""), status, qa)


def render_daily_report_markdown(report: Mapping[str, Any], *, title: str = TITLE) -> str:
    view = build_daily_report_view(report)
    lines = [
        f"# {title}",
        "",
        f"日期：{view.date_utc}",
        f"状态：{view.status}",
        "",
    ]
    for question, answer in view.questions:
        lines.extend([f"Q：{question}", f"A：{answer}", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_daily_report_feishu(report: Mapping[str, Any], *, title: str = TITLE, test: bool = False) -> str:
    rendered_title = f"【测试】{title}" if test else title
    return render_daily_report_markdown(report, title=rendered_title)


def daily_status(report: Mapping[str, Any]) -> str:
    runtime = mapping(report.get("runtime"))
    lifecycle = str(runtime.get("lifecycle_state") or "")
    if lifecycle:
        return lifecycle
    if mapping(report.get("data_quality")).get("account_execution_ready") is True:
        return "PAPER_READY"
    return "NOT_READY"


def system_answer(status: str, quality: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    if status == "PAPER_READY":
        return "正常。Paper account、数据新鲜度和执行门禁已通过，可以按现有 risk gate 运行。"
    if status == "MARKET_CLOSED_WAITING":
        return "处于等待状态。当前美国市场已收盘，系统未进入执行状态，这是预期的保护行为。"
    if status == "SAFE_MODE":
        return "不正常，系统处于 SAFE_MODE。订单执行已关闭，需要先处理 blocker。"
    blockers = compact_blockers(quality.get("blocking_reasons"), runtime.get("blocked_reason"), limit=2)
    return "未完全正常。主要 blocker：" + "；".join(blockers) if blockers else "未完全正常。当前未通过 PAPER_READY。"


def ibkr_answer(runtime: Mapping[str, Any]) -> str:
    connected = runtime.get("ibkr_connected")
    execution_enabled = runtime.get("execution_enabled")
    if connected is True:
        return f"连接正常。IBKR/TWS 已连接；execution_enabled={str(execution_enabled).lower()}。"
    if connected is False:
        return "未连接。IBKR/TWS 当前不可用于订单执行。"
    return "暂时无法确认，IBKR/TWS 状态为 UNKNOWN。"


def account_answer(snapshot: Mapping[str, Any]) -> str:
    return (
        f"净资产 {money(field_value(snapshot, 'net_liquidation'))}，"
        f"现金 {money(field_value(snapshot, 'total_cash_value'))}，"
        f"Buying Power {money(field_value(snapshot, 'buying_power'))}，"
        f"Available Funds {money(field_value(snapshot, 'available_funds'))}。"
    )


def pnl_answer(snapshot: Mapping[str, Any]) -> str:
    daily = snapshot_field(snapshot, "daily_pnl")
    daily_text = "DailyPnL 暂缺（MISSING）" if daily.get("freshness") == "MISSING" else f"DailyPnL {money(daily.get('value'))}"
    return f"{daily_text}；Realized {money(field_value(snapshot, 'realized_pnl'))}；Unrealized {money(field_value(snapshot, 'unrealized_pnl'))}。"


def positions_answer(positions: list[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> str:
    long_count = sum(float_or_zero(row.get("quantity")) > 0 for row in positions)
    short_count = sum(float_or_zero(row.get("quantity")) < 0 for row in positions)
    return f"共 {len(positions)} 个持仓，总敞口约 {money(field_value(snapshot, 'gross_exposure'))}；long {long_count} / short {short_count}。"


def protection_answer(positions: list[Mapping[str, Any]], coverage: list[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> str:
    quality = mapping(snapshot.get("data_quality"))
    if not coverage or quality.get("protection_coverage_fresh") is not True:
        state = "MISSING" if not coverage else "STALE"
        return f"暂时无法确认，protection data = {state}。"
    long_symbols = {str(row.get("symbol") or "").upper() for row in positions if float_or_zero(row.get("quantity")) > 0}
    relevant = [row for row in coverage if str(row.get("symbol") or "").upper() in long_symbols]
    covered = sum(row.get("covered") is True for row in relevant)
    if covered == len(relevant) and relevant:
        return f"是。{len(relevant)} 个 long positions 中 {covered} 个确认存在有效保护。"
    return f"没有。{len(relevant)} 个 long positions 中 {covered} 个确认存在有效保护，当前 protection coverage = {covered}/{len(relevant)}。"


def market_data_answer(report: Mapping[str, Any], market_state: str, quality: Mapping[str, Any]) -> str:
    account_snapshot = mapping(report.get("account_snapshot"))
    positions = list_of_mappings(account_snapshot.get("positions"))
    total = len(positions)
    ready = bool(quality.get("quotes_ready"))
    blockers = compact_blockers(quality.get("blocking_reasons"), limit=1)
    closed = daily_status(report) == "MARKET_CLOSED_WAITING" or market_state.upper() == "CLOSED"
    if closed:
        reason = "outside_session_no_quote"
        return f"当前美国市场已收盘，{total} 个持仓 live bid/ask = 0/{total}；诊断为 {reason}，目前不视为行情故障。"
    if ready:
        return "正常。执行级 live bid/ask 已满足当前门禁。"
    return f"异常。当前处于交易时段，但 live bid/ask coverage = 0/{total}。"


def strategy_answer(funnel: Mapping[str, Any]) -> str:
    return f"strategy decisions {int_value(funnel.get('strategy_decisions'))}；order intents {int_value(funnel.get('order_intents'))}；risk rejects {int_value(funnel.get('risk_rejected'))}。"


def orders_answer(funnel: Mapping[str, Any]) -> str:
    keys = ["submitted", "broker_ack", "partial_fill", "filled", "executions", "commissions"]
    if all(int_value(funnel.get(key)) == 0 for key in keys):
        return "没有。今日 order requests、broker orders 和 executions 均为 0。"
    return (
        f"submitted {int_value(funnel.get('submitted'))}；broker acknowledged {int_value(funnel.get('broker_ack'))}；"
        f"partial fills {int_value(funnel.get('partial_fill'))}；fills {int_value(funnel.get('filled'))}；"
        f"executions {int_value(funnel.get('executions'))}；commission events {int_value(funnel.get('commissions'))}。"
    )


def no_order_answer(report: Mapping[str, Any], quality: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    if daily_status(report) == "MARKET_CLOSED_WAITING":
        return "当前为 MARKET_CLOSED_WAITING，美国市场已收盘，因此 execution_enabled=false。"
    blockers = compact_blockers(quality.get("blocking_reasons"), runtime.get("blocked_reason"), limit=2)
    return "主要原因：" + "；".join(blockers) + "。" if blockers else "没有可提交订单；策略、行情或风控没有形成可执行路径。"


def mode9_answer(runtime: Mapping[str, Any]) -> str:
    state = str(runtime.get("lifecycle_state") or "UNKNOWN")
    if state in {"MARKET_CLOSED_WAITING", "SAFE_MODE"}:
        return f"{state}。Mode 9 完成了最近周期，但当前不应执行订单。"
    if runtime.get("mode9_running") is True:
        return "RUNNING。Mode 9 当前有活动进程。"
    if runtime.get("mode9_running") is False:
        return "STOPPED。当前未检测到 Mode 9 活动进程。"
    return "UNKNOWN。当前报告没有足够进程证据。"


def paper_ready_answer(report: Mapping[str, Any], quality: Mapping[str, Any], runtime: Mapping[str, Any], positions: list[Mapping[str, Any]], coverage: list[Mapping[str, Any]]) -> str:
    if quality.get("account_execution_ready") is True and daily_status(report) == "PAPER_READY":
        return "是。PAPER_READY 已通过。"
    blockers = paper_ready_blockers(report, quality, runtime, positions, coverage)
    return "否。当前主要 blocker：" + "；".join(f"{index + 1}. {item}" for index, item in enumerate(blockers)) + "。"


def next_steps_answer(report: Mapping[str, Any], quality: Mapping[str, Any], runtime: Mapping[str, Any], positions: list[Mapping[str, Any]], coverage: list[Mapping[str, Any]]) -> str:
    return "；".join(paper_ready_blockers(report, quality, runtime, positions, coverage)[:3]) + "。"


def paper_ready_blockers(report: Mapping[str, Any], quality: Mapping[str, Any], runtime: Mapping[str, Any], positions: list[Mapping[str, Any]], coverage: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if daily_status(report) == "MARKET_CLOSED_WAITING":
        blockers.append("等待正常交易时段重新验证 live L1")
    uncovered = uncovered_long_summary(positions, coverage, mapping(mapping(report.get("account_snapshot")).get("data_quality")))
    if uncovered:
        blockers.append(uncovered)
    if snapshot_field(mapping(report.get("account_snapshot")), "daily_pnl").get("freshness") == "MISSING":
        blockers.append("DailyPnL MISSING")
    blockers.extend(compact_blockers(quality.get("blocking_reasons"), runtime.get("blocked_reason"), limit=3))
    return list(dict.fromkeys(blockers))[:3] or ["PAPER_READY 未通过"]


def uncovered_long_summary(positions: list[Mapping[str, Any]], coverage: list[Mapping[str, Any]], quality: Mapping[str, Any]) -> str:
    if not coverage or quality.get("protection_coverage_fresh") is not True:
        return ""
    long_symbols = {str(row.get("symbol") or "").upper() for row in positions if float_or_zero(row.get("quantity")) > 0}
    relevant = [row for row in coverage if str(row.get("symbol") or "").upper() in long_symbols]
    uncovered = sum(float_or_zero(row.get("uncovered_qty")) > 0 for row in relevant)
    return f"{uncovered}/{len(relevant)} existing long positions uncovered" if relevant and uncovered else ""


def compact_blockers(*values: Any, limit: int = 3) -> list[str]:
    raw: list[str] = []
    for value in values:
        if isinstance(value, list):
            raw.extend(str(item) for item in value if item)
        elif value:
            raw.append(str(value))
    normalized = [human_blocker(item) for item in raw]
    return list(dict.fromkeys(item for item in normalized if item))[:limit]


def human_blocker(text: str) -> str:
    if "market_closed_no_live_bid_ask_expected" in text:
        return "当前美国市场已收盘，没有实时 bid/ask 属于预期情况"
    if "EXECUTION_GATE blocks SELL execution because bid is missing or has no age" in text:
        return "交易时段缺少 fresh bid，Execution Gate 已阻止 SELL execution"
    if "quotes missing" in text:
        return "live L1 quote missing"
    return re.sub(r"\s+", " ", text).strip()[:160]


def snapshot_field(snapshot: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return mapping(snapshot.get(key))


def field_value(snapshot: Mapping[str, Any], key: str) -> Any:
    return snapshot_field(snapshot, key).get("value")


def money(value: Any) -> str:
    if value in (None, "", "MISSING"):
        return "MISSING"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def read_daily_report(path: Path | None = None) -> dict[str, Any]:
    target = path or PROJECT_ROOT / "reports" / "daily_trading" / "latest.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
