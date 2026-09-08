"""Deterministic HTML visual report renderer for Paper Trading daily diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.production_paths import REPORT_ROOT

from scripts.daily_trading_report_view import (
    compact_blockers,
    daily_status,
    field_value,
    float_or_zero,
    int_value,
    list_of_mappings,
    mapping,
    money,
    paper_ready_blockers,
    snapshot_field,
)


REPORT_DIR = REPORT_ROOT / "daily_trading"
DEFAULT_WIDTH = 1440
DEFAULT_HEIGHT = 900
BUNDLED_NODE = Path("/Users/nbhsbgnb/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
BUNDLED_NODE_MODULES = Path("/Users/nbhsbgnb/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules")


@dataclass(frozen=True)
class VisualReportViewModel:
    title: str
    report_date: str
    trading_date: str
    generated_at: str
    status: str
    status_label: str
    status_class: str
    paper_ready: str
    net_liquidation: str
    total_cash_value: str
    buying_power: str
    available_funds: str
    daily_pnl: str
    realized_pnl: str
    unrealized_pnl: str
    position_count: int
    gross_exposure: str
    net_exposure: str
    open_orders: int
    order_requests: int
    executions: int
    fills: int
    protection_text: str
    protection_status: str
    protection_class: str
    l1_text: str
    l1_status: str
    l1_class: str
    blockers: list[str]
    chart_points: list[dict[str, object]]
    chart_available: bool
    sanitized_account_id: str


def read_daily_report(path: Path = REPORT_DIR / "latest.json") -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_visual_report_view_model(report: Mapping[str, Any], *, history_dir: Path = REPORT_DIR) -> VisualReportViewModel:
    snapshot = mapping(report.get("account_snapshot"))
    quality = mapping(report.get("data_quality"))
    runtime = mapping(report.get("runtime"))
    funnel = mapping(report.get("lifecycle_funnel"))
    positions = list_of_mappings(snapshot.get("positions"))
    coverage = list_of_mappings(snapshot.get("protective_order_coverage"))
    status = normalize_status(daily_status(report), runtime)
    protection_text, protection_status, protection_class = protection_summary(positions, coverage, snapshot)
    l1_text, l1_status, l1_class = l1_summary(report, quality, positions)
    blockers = paper_ready_blockers(report, quality, runtime, positions, coverage)
    chart_points = seven_day_history(history_dir)
    return VisualReportViewModel(
        title="买 der · Paper Trading 日报",
        report_date=str(report.get("date_utc") or ""),
        trading_date=str(report.get("trading_date") or report.get("date_utc") or ""),
        generated_at=str(report.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        status=status,
        status_label=status.replace("_", " "),
        status_class=status_class(status),
        paper_ready="YES" if quality.get("account_execution_ready") is True and status == "PAPER_READY" else "NO",
        net_liquidation=money(field_value(snapshot, "net_liquidation")),
        total_cash_value=money(field_value(snapshot, "total_cash_value")),
        buying_power=money(field_value(snapshot, "buying_power")),
        available_funds=money(field_value(snapshot, "available_funds")),
        daily_pnl=pnl_text(snapshot, "daily_pnl"),
        realized_pnl=pnl_text(snapshot, "realized_pnl"),
        unrealized_pnl=pnl_text(snapshot, "unrealized_pnl"),
        position_count=len(positions),
        gross_exposure=money(field_value(snapshot, "gross_exposure")),
        net_exposure=money(field_value(snapshot, "net_exposure")),
        open_orders=len(list_of_mappings(snapshot.get("open_orders"))),
        order_requests=int_value(funnel.get("submitted")),
        executions=int_value(funnel.get("executions")),
        fills=int_value(funnel.get("filled")),
        protection_text=protection_text,
        protection_status=protection_status,
        protection_class=protection_class,
        l1_text=l1_text,
        l1_status=l1_status,
        l1_class=l1_class,
        blockers=blockers[:3],
        chart_points=chart_points,
        chart_available=len(chart_points) >= 2,
        sanitized_account_id=str(mapping(snapshot.get("account_id")).get("value") or ""),
    )


def normalize_status(status: str, runtime: Mapping[str, Any]) -> str:
    if runtime.get("auth_required") is True:
        return "AUTH_REQUIRED"
    if runtime.get("api_reconnecting") is True:
        return "API_RECONNECTING"
    allowed = {"PAPER_READY", "MARKET_CLOSED_WAITING", "SAFE_MODE", "AUTH_REQUIRED", "API_RECONNECTING", "UNKNOWN"}
    if status in allowed:
        return status
    if status in {"IBKR_DISCONNECTED", "NOT_READY"}:
        return "UNKNOWN"
    return status or "UNKNOWN"


def status_class(status: str) -> str:
    return {
        "PAPER_READY": "ok",
        "MARKET_CLOSED_WAITING": "wait",
        "SAFE_MODE": "bad",
        "AUTH_REQUIRED": "warn",
        "API_RECONNECTING": "warn",
        "UNKNOWN": "unknown",
    }.get(status, "unknown")


def pnl_text(snapshot: Mapping[str, Any], key: str) -> str:
    field = snapshot_field(snapshot, key)
    if field.get("freshness") == "MISSING" or field.get("value") == "MISSING":
        return "MISSING"
    return money(field.get("value"))


def protection_summary(
    positions: Sequence[Mapping[str, Any]],
    coverage: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> tuple[str, str, str]:
    quality = mapping(snapshot.get("data_quality"))
    if not coverage:
        return "Protection: MISSING", "UNKNOWN", "unknown"
    if quality.get("protection_coverage_fresh") is not True:
        return "Protection: STALE", "PENDING", "warn"
    long_symbols = {str(row.get("symbol") or "").upper() for row in positions if float_or_zero(row.get("quantity")) > 0}
    relevant = [row for row in coverage if str(row.get("symbol") or "").upper() in long_symbols]
    if not relevant:
        return "Protection: UNKNOWN", "UNKNOWN", "unknown"
    covered = sum(row.get("covered") is True for row in relevant)
    text = f"{covered} / {len(relevant)}"
    if covered == len(relevant):
        return text, "PROTECTED", "ok"
    return text, "UNPROTECTED", "bad"


def l1_summary(report: Mapping[str, Any], quality: Mapping[str, Any], positions: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    total = len(positions)
    market_state = str(mapping(report.get("runtime")).get("market_session_state") or "")
    closed = daily_status(report) == "MARKET_CLOSED_WAITING" or market_state.upper() == "CLOSED"
    if closed:
        return f"L1 0/{total} · Market closed — expected", "EXPECTED", "wait"
    if quality.get("quotes_ready") is True:
        return f"L1 {total}/{total}", "OK", "ok"
    return f"L1 0/{total}", "ERROR", "bad"


def seven_day_history(history_dir: Path) -> list[dict[str, object]]:
    rows: list[tuple[str, float | None, float | None]] = []
    for path in sorted(history_dir.glob("*.json")):
        if path.name == "latest.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = str(payload.get("trading_date") or payload.get("date_utc") or path.stem)
        net_liq = numeric(field_value(mapping(payload.get("account_snapshot")), "net_liquidation"))
        daily_pnl = numeric(field_value(mapping(payload.get("account_snapshot")), "daily_pnl"))
        if net_liq is not None or daily_pnl is not None:
            rows.append((day, net_liq, daily_pnl))
    points = [
        {"date": day, "net_liquidation": net_liq, "daily_pnl": daily_pnl}
        for day, net_liq, daily_pnl in rows[-7:]
    ]
    return points


def render_html(report: Mapping[str, Any], *, history_dir: Path = REPORT_DIR) -> str:
    vm = build_visual_report_view_model(report, history_dir=history_dir)
    return html_document(vm)


def html_document(vm: VisualReportViewModel) -> str:
    css = """
*{box-sizing:border-box} body{margin:0;background:#f5f7fb;color:#101828;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",Arial,sans-serif}
.page{width:1440px;height:900px;padding:42px;overflow:hidden}
.header{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:24px}
h1{font-size:44px;line-height:1;margin:0 0 14px;font-weight:780}.meta{font-size:18px;color:#475467;line-height:1.55}
.status{min-width:340px;border-radius:26px;padding:24px;background:#fff;box-shadow:0 10px 30px rgba(16,24,40,.08);border-left:14px solid #98a2b3}
.status.ok{border-color:#12b76a}.status.wait{border-color:#f79009}.status.warn{border-color:#fdb022}.status.bad{border-color:#f04438}
.status .label{font-size:30px;font-weight:800}.status .sub{font-size:17px;color:#475467;margin-top:8px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{background:#fff;border-radius:24px;padding:22px;box-shadow:0 10px 30px rgba(16,24,40,.07);min-height:120px}
.card h2{font-size:17px;color:#667085;margin:0 0 12px;font-weight:700}.value{font-size:32px;font-weight:800;letter-spacing:-.02em}.small{font-size:20px;font-weight:760}.hint{font-size:16px;color:#667085;margin-top:8px}
.section{margin-top:18px;display:grid;grid-template-columns:1.1fr 1.1fr 1fr;gap:16px}.wide{grid-column:span 2}.blockers ol{margin:10px 0 0 24px;padding:0;font-size:20px;line-height:1.48}.badge{display:inline-block;border-radius:999px;padding:8px 14px;font-size:16px;font-weight:800;margin-top:10px}
.badge.ok{background:#dcfae6;color:#067647}.badge.wait{background:#fef0c7;color:#b54708}.badge.warn{background:#fef0c7;color:#b54708}.badge.bad{background:#fee4e2;color:#b42318}.badge.unknown{background:#eaecf0;color:#344054}
.chart{height:178px;margin-top:8px}.foot{position:absolute;left:42px;right:42px;bottom:22px;color:#98a2b3;font-size:14px}
svg text{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",Arial,sans-serif}
"""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1440,initial-scale=1">
<title>{e(vm.title)}</title><style>{css}</style></head>
<body><main class="page">
  <section class="header">
    <div><h1>{e(vm.title)}</h1>
      <div class="meta">Report date: {e(vm.report_date)} · Trading date: {e(vm.trading_date)}<br>Generated at: {e(vm.generated_at)} · Account: {e(vm.sanitized_account_id or "MISSING")}</div>
    </div>
    <div class="status {e(vm.status_class)}"><div class="label">{e(vm.status_label)}</div><div class="sub">PAPER_READY: {e(vm.paper_ready)}</div></div>
  </section>
  <section class="grid">
    {kpi("Net Liquidation", vm.net_liquidation)}
    {kpi("Cash / TotalCashValue", vm.total_cash_value)}
    {kpi("Buying Power", vm.buying_power)}
    {kpi("Available Funds", vm.available_funds)}
    {kpi("DailyPnL", vm.daily_pnl)}
    {kpi("RealizedPnL", vm.realized_pnl)}
    {kpi("UnrealizedPnL", vm.unrealized_pnl)}
    {kpi("Positions", str(vm.position_count), f"Gross {vm.gross_exposure} · Net {vm.net_exposure}")}
  </section>
  <section class="section">
    <div class="card"><h2>Trading Status</h2><div class="value small">Orders: {vm.order_requests}</div><div class="hint">Open Orders {vm.open_orders} · Executions {vm.executions} · Fills {vm.fills}</div></div>
    <div class="card"><h2>Protection Coverage</h2><div class="value">{e(vm.protection_text)}</div><span class="badge {e(vm.protection_class)}">{e(vm.protection_status)}</span></div>
    <div class="card"><h2>Market Data</h2><div class="value small">{e(vm.l1_text)}</div><span class="badge {e(vm.l1_class)}">{e(vm.l1_status)}</span></div>
    <div class="card blockers"><h2>Readiness Blockers</h2>{blockers_html(vm.blockers)}</div>
    <div class="card wide"><h2>7-day Net Liquidation / PnL Trend</h2>{chart_html(vm.chart_points) if vm.chart_available else '<div class="value small">Not enough history</div>'}</div>
  </section>
  <div class="foot">Deterministic renderer · Source: DailyReport JSON / AccountSnapshot · No LLM · No broker reconnect</div>
</main></body></html>"""


def kpi(label: str, value: str, hint: str = "") -> str:
    hint_html = f'<div class="hint">{e(hint)}</div>' if hint else ""
    return f'<div class="card"><h2>{e(label)}</h2><div class="value">{e(value)}</div>{hint_html}</div>'


def blockers_html(blockers: Sequence[str]) -> str:
    items = "".join(f"<li>{e(item)}</li>" for item in blockers[:3])
    return f"<ol>{items}</ol>" if items else '<div class="value small">None</div>'


def chart_html(points: Sequence[Mapping[str, object]]) -> str:
    width, height, pad = 840, 178, 30
    values = [numeric(p.get("net_liquidation")) for p in points if numeric(p.get("net_liquidation")) is not None]
    if len(values) < 2:
        return '<div class="value small">Not enough history</div>'
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    coords = []
    valid = [p for p in points if numeric(p.get("net_liquidation")) is not None]
    for i, p in enumerate(valid):
        x = pad + i * ((width - 2 * pad) / max(1, len(valid) - 1))
        y = height - pad - ((numeric(p.get("net_liquidation")) - lo) / span) * (height - 2 * pad)
        coords.append((x, y, str(p.get("date") or "")))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in coords)
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#1570ef"/>' for x, y, _ in coords)
    labels = "".join(f'<text x="{x:.1f}" y="{height-6}" text-anchor="middle" font-size="13" fill="#667085">{e(label[-5:])}</text>' for x, _, label in coords)
    return f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="7 day net liquidation trend"><polyline points="{poly}" fill="none" stroke="#1570ef" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>{circles}{labels}<text x="{pad}" y="18" font-size="13" fill="#667085">{lo:,.0f}</text><text x="{width-pad}" y="18" text-anchor="end" font-size="13" fill="#667085">{hi:,.0f}</text></svg>'


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


def numeric(value: object) -> float | None:
    if value in (None, "", "MISSING"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", header[16:24])


def write_visual_report(
    report_path: Path = REPORT_DIR / "latest.json",
    *,
    output_dir: Path = REPORT_DIR,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    node_bin: Path | None = None,
    node_modules: Path | None = None,
) -> dict[str, Any]:
    report = read_daily_report(report_path)
    vm = build_visual_report_view_model(report, history_dir=output_dir)
    html_text = html_document(vm)
    output_dir.mkdir(parents=True, exist_ok=True)
    dated_html = output_dir / f"{vm.trading_date}.html"
    dated_png = output_dir / f"{vm.trading_date}.png"
    latest_html = output_dir / "latest.html"
    latest_png = output_dir / "latest.png"
    latest_html.write_text(html_text, encoding="utf-8")
    dated_html.write_text(html_text, encoding="utf-8")
    render_png(latest_html, latest_png, width=width, height=height, node_bin=node_bin, node_modules=node_modules)
    dated_png.write_bytes(latest_png.read_bytes())
    manifest = visual_manifest(report_path, latest_html, latest_png, report, vm, width=width, height=height)
    write_manifest(output_dir, manifest, vm.trading_date)
    validate_manifest_consistency(manifest, report, vm)
    return manifest


def render_png(
    html_path: Path,
    png_path: Path,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    node_bin: Path | None = None,
    node_modules: Path | None = None,
) -> None:
    node = node_bin or Path(os.getenv("VISUAL_REPORT_NODE", str(BUNDLED_NODE)))
    modules = node_modules or Path(os.getenv("NODE_PATH", str(BUNDLED_NODE_MODULES)))
    script = PROJECT_ROOT / "scripts" / "render_html_to_png.js"
    env = os.environ.copy()
    env["NODE_PATH"] = str(modules)
    result = subprocess.run(
        [str(node), str(script), str(html_path), str(png_path), str(width), str(height)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "HTML to PNG render failed").strip()
        raise RuntimeError(message[:500])


def visual_manifest(
    report_path: Path,
    html_path: Path,
    png_path: Path,
    report: Mapping[str, Any],
    vm: VisualReportViewModel,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    actual_width, actual_height = png_dimensions(png_path)
    return {
        "source_report_path": str(report_path),
        "source_report_hash": sha256_file(report_path),
        "rendered_at": datetime.now(timezone.utc).isoformat(),
        "html_path": str(html_path),
        "image_path": str(png_path),
        "image_size": png_path.stat().st_size,
        "image_width": actual_width,
        "image_height": actual_height,
        "expected_width": width,
        "expected_height": height,
        "report_date": str(report.get("date_utc") or ""),
        "trading_date": vm.trading_date,
        "account_id": vm.sanitized_account_id,
        "net_liquidation": vm.net_liquidation,
        "daily_pnl": vm.daily_pnl,
        "realized_pnl": vm.realized_pnl,
        "unrealized_pnl": vm.unrealized_pnl,
        "position_count": vm.position_count,
        "paper_ready": vm.paper_ready,
        "blockers": list(vm.blockers),
    }


def validate_manifest_consistency(manifest: Mapping[str, Any], report: Mapping[str, Any], vm: VisualReportViewModel) -> None:
    checks = {
        "report_date": str(report.get("date_utc") or ""),
        "trading_date": vm.trading_date,
        "account_id": vm.sanitized_account_id,
        "net_liquidation": vm.net_liquidation,
        "daily_pnl": vm.daily_pnl,
        "realized_pnl": vm.realized_pnl,
        "unrealized_pnl": vm.unrealized_pnl,
        "position_count": vm.position_count,
        "paper_ready": vm.paper_ready,
    }
    for key, expected in checks.items():
        if manifest.get(key) != expected:
            raise ValueError(f"manifest mismatch for {key}")
    if manifest.get("image_size", 0) <= 0:
        raise ValueError("PNG image is empty")
    if manifest.get("image_width") != manifest.get("expected_width") or manifest.get("image_height") != manifest.get("expected_height"):
        raise ValueError("PNG dimensions do not match expected size")


def write_manifest(output_dir: Path, manifest: Mapping[str, Any], trading_date: str) -> None:
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    (output_dir / "visual_report_manifest.json").write_text(text, encoding="utf-8")
    (output_dir / f"{trading_date}.visual_manifest.json").write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_DIR / "latest.json")
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = write_visual_report(args.report, output_dir=args.output_dir, width=args.width, height=args.height)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
