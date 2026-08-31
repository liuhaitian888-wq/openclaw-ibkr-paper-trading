#!/usr/bin/env python3
"""Build the v0.1.0 Foundation Baseline engineering manual.

The script is intentionally read-only with respect to trading runtime state. It
does not import or call runtime entry points that connect to TWS or submit
orders. It only inspects repository files, Git metadata, SQLite schema, logs,
and generated reports.
"""

from __future__ import annotations

import ast
import csv
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MANUAL_ROOT = ROOT / "docs" / "manual"
GENERATED = MANUAL_ROOT / "generated"
DIAGRAMS = MANUAL_ROOT / "diagrams"
OUTPUT_PDF = ROOT / "output" / "pdf" / "ibkr_paper_trading_engineering_manual_v0.1.0_cn.pdf"
FACTS_PATH = GENERATED / "manual_facts.json"

MANUAL_VERSION = "v0.1.0"
RELEASE_NAME = "Foundation Baseline"
CHINESE_NAME = "初始架构基线版"
VALIDATION_STATUS = "Draft / Not yet fully system-validated"

COLOR = {
    "data": "#2F80ED",
    "runtime": "#27AE60",
    "risk": "#D64545",
    "execution": "#F2994A",
    "persistence": "#7B61FF",
    "review": "#D7A21D",
    "external": "#6B7280",
    "ink": "#1F2937",
    "muted": "#6B7280",
    "line": "#D1D5DB",
}

CHAPTERS = [
    "Project Introduction",
    "How to Read This Manual",
    "System Overview",
    "Complete System Architecture",
    "Runtime Lifecycle",
    "Data Flow, Signal Flow, Control Flow, and Error Flow",
    "Module Communication Contract",
    "Six-Layer Stock Pool",
    "IBKR/TWS Integration",
    "Risk and Execution Architecture",
    "Database Architecture",
    "Log and Observability Architecture",
    "Autonomous Review Framework",
    "Failure and Recovery Scenarios",
    "Developer Operations",
    "Source-Code Reference",
    "Appendix",
]


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[str]
    row_count: int
    primary_key: str
    writer: str
    readers: str
    purpose: str


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def extract_pool_layers() -> list[str]:
    src = (ROOT / "trading" / "pool_state.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "LAYERS":
                    return [ast.literal_eval(elt) for elt in node.value.elts]
    return []


def classify_table(name: str) -> tuple[str, str, str, str]:
    if "order_requests" == name:
        return (
            "idempotency_key",
            "trading/audit.py",
            "trading/service.py, API audit endpoints, developer diagnostics",
            "Idempotent order reservation and status ledger.",
        )
    if name in {"canonical_pool_state", "canonical_pool_transition_events", "pool_membership_history"}:
        return (
            "symbol or transition/event id when present",
            "trading/pool_state.py, trading/pool_manager.py, auto-open pipeline",
            "pool reports, strategy selection, autonomous review",
            "Canonical stock-pool membership, transitions, and layer state.",
        )
    if name.endswith("_events") or name == "event_store":
        return (
            "event_id when present; otherwise append-only rowid",
            "module-specific event writers via trading/paper_audit_db.py or SQLiteEventStore",
            "reports, review collector, replay diagnostics",
            "Append-only runtime event evidence.",
        )
    if "pnl" in name:
        return (
            "trading_date/timestamp/symbol depending on table",
            "account/PnL report builders",
            "risk review, performance review, account dashboard",
            "PnL snapshots, summaries, and attribution evidence.",
        )
    if "candidate" in name or "scanner" in name or "news" in name:
        return (
            "timestamp/discovery_run_id/symbol",
            "discovery, scanner, news, candidate scoring modules",
            "pool manager, strategy review, AI review pipeline",
            "Discovery and candidate-selection evidence.",
        )
    return (
        "not declared as SQLite PRIMARY KEY unless noted by schema",
        "module-specific writer",
        "diagnostic reports and review tools",
        "Runtime evidence table.",
    )


def sqlite_schema() -> list[TableInfo]:
    db = ROOT / "trading_audit.sqlite3"
    if not db.exists():
        return []
    tables: list[TableInfo] = []
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            columns = [row["name"] for row in con.execute(f"PRAGMA table_info({name})")]
            try:
                row_count = int(con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            except sqlite3.DatabaseError:
                row_count = -1
            pk, writer, readers, purpose = classify_table(name)
            pk_columns = [row["name"] for row in con.execute(f"PRAGMA table_info({name})") if row["pk"]]
            if pk_columns:
                pk = ", ".join(pk_columns)
            tables.append(TableInfo(name, columns, row_count, pk, writer, readers, purpose))
    return tables


def source_reference() -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for base in ["trading", "scripts", "tests"]:
        for path in sorted((ROOT / base).glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = ast.Module(body=[])
            classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
            funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            doc = ast.get_docstring(tree) or "Project file."
            refs.append(
                {
                    "path": rel(path),
                    "purpose": " ".join(doc.split())[:180],
                    "classes": ", ".join(classes[:6]),
                    "functions": ", ".join(funcs[:10]),
                }
            )
    return refs


def report_inventory() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((ROOT / "reports").glob("**/latest.json"))[:220]:
        data = read_json(path)
        keys = list(data.keys())[:12] if isinstance(data, dict) else []
        records.append({"path": rel(path), "keys": keys})
    for path in sorted((ROOT / "logs").glob("*.log")):
        records.append({"path": rel(path), "size": path.stat().st_size})
    return records


def data_inventory() -> list[dict[str, Any]]:
    rows = []
    for path in sorted((ROOT / "data").glob("*")):
        item: dict[str, Any] = {"path": rel(path), "size_bytes": path.stat().st_size}
        if path.suffix.lower() == ".csv":
            try:
                with path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.reader(handle)
                    header = next(reader, [])
                    count = sum(1 for _ in reader)
                item.update({"columns": header, "row_count_without_header": count})
            except Exception:
                pass
        rows.append(item)
    return rows


def git_facts() -> dict[str, str]:
    commit = run(["git", "rev-parse", "HEAD"])
    branch = run(["git", "branch", "--show-current"])
    remote = run(["git", "remote", "get-url", "origin"])
    status = run(["git", "status", "--short"])
    commit_url = ""
    if remote.startswith("git@github.com:") and commit:
        repo = remote.removeprefix("git@github.com:").removesuffix(".git")
        commit_url = f"https://github.com/{repo}/commit/{commit}"
    elif remote.startswith("https://github.com/") and commit:
        commit_url = f"{remote.removesuffix('.git')}/commit/{commit}"
    return {
        "git_commit": commit,
        "git_branch": branch,
        "git_remote": remote,
        "git_commit_url": commit_url,
        "git_status_short": status,
    }


def collect_facts() -> dict[str, Any]:
    tables = sqlite_schema()
    sqlite_health = "ok"
    try:
        with sqlite3.connect(ROOT / "trading_audit.sqlite3") as con:
            con.execute("PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as exc:
        sqlite_health = f"quick_check_failed: {exc}"
    facts = {
        "manual_version": MANUAL_VERSION,
        "release_name": RELEASE_NAME,
        "chinese_name": CHINESE_NAME,
        "validation_status": VALIDATION_STATUS,
        "generation_date_utc": datetime.now(timezone.utc).isoformat(),
        "chapters": CHAPTERS,
        "pool_layers": extract_pool_layers(),
        "sqlite_database": str(ROOT / "trading_audit.sqlite3"),
        "sqlite_table_count": len(tables),
        "sqlite_health": sqlite_health,
        "sqlite_tables": [table.__dict__ for table in tables],
        "source_reference": source_reference(),
        "report_inventory": report_inventory(),
        "data_inventory": data_inventory(),
        "repository_paths": [
            "docs/PROJECT_HANDOFF_MANUAL_CN.md",
            "docs/PROJECT_MAP.md",
            "ARCHITECTURE.md",
            "SECURITY_MODEL.md",
            "TRADING_LOCK.md",
            "trading/pool_state.py",
            "trading/paper_audit_db.py",
            "trading/tws_paper.py",
            "trading/service.py",
            "trading/risk.py",
            "trading/autonomous_runtime.py",
            "reports/mode9_infrastructure_status/latest.json",
            "reports/sqlite_audit/latest.json",
            "logs/trading_api.log",
            "logs/autonomous_agent.log",
            "trading_audit.sqlite3",
        ],
        "manual_confirmation_required": [
            "Full system validation remains incomplete for this draft baseline.",
            "Some retention/cleanup policies are not encoded in source and are documented as not yet formalized.",
            "TWS desktop/API settings must be confirmed from the TWS UI during an operational run.",
            "Report-only modules marked NOT_STARTED or not connected in Mode 9 reports require owner prioritization.",
        ],
    }
    facts.update(git_facts())
    GENERATED.mkdir(parents=True, exist_ok=True)
    FACTS_PATH.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")
    return facts


def write_svg(name: str, title: str, nodes: list[tuple[int, int, int, int, str, str]], edges: list[tuple[int, int]]) -> None:
    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    width, height = 1100, 620
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="40" y="46" font-size="28" font-family="Arial" fill="{COLOR["ink"]}">{title}</text>',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#6B7280"/></marker></defs>',
    ]
    for a, b in edges:
        ax, ay, aw, ah, _, _ = nodes[a]
        bx, by, bw, bh, _, _ = nodes[b]
        parts.append(f'<line x1="{ax+aw}" y1="{ay+ah/2}" x2="{bx}" y2="{by+bh/2}" stroke="#6B7280" stroke-width="2.5" marker-end="url(#arrow)"/>')
    for x, y, w, h, label, color in nodes:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{color}" fill-opacity="0.13" stroke="{color}" stroke-width="2"/>')
        safe = label.replace("&", "&amp;")
        for i, line in enumerate(safe.split("\\n")):
            parts.append(f'<text x="{x+16}" y="{y+30+i*22}" font-size="17" font-family="Arial" fill="{COLOR["ink"]}">{line}</text>')
    parts.append("</svg>")
    (DIAGRAMS / name).write_text("\n".join(parts), encoding="utf-8")


def build_diagrams() -> list[dict[str, Any]]:
    specs = [
        ("complete_system_mind_map.svg", "Complete System Mind Map", [
            (60, 110, 170, 72, "User/API\\nControl", COLOR["execution"]),
            (300, 80, 180, 72, "Mode 9 Runtime\\nScheduler", COLOR["runtime"]),
            (550, 70, 180, 72, "Data + Research\\nScanner/News", COLOR["data"]),
            (550, 190, 180, 72, "Strategy + Pool\\nSix layers", COLOR["runtime"]),
            (790, 150, 170, 72, "Risk Gates\\nPaper-only", COLOR["risk"]),
            (790, 280, 170, 72, "Execution\\nTWS adapter", COLOR["execution"]),
            (550, 360, 180, 72, "SQLite/Reports\\nLogs", COLOR["persistence"]),
            (300, 390, 180, 72, "AI Review\\nEvidence replay", COLOR["review"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,1)]),
        ("layered_system_architecture.svg", "Layered System Architecture", [
            (110, 90, 820, 48, "User/control layer: menu, API, scripts, safety lock", COLOR["execution"]),
            (110, 155, 820, 48, "Runtime and scheduler: Mode 9, process guard, lifecycle loop", COLOR["runtime"]),
            (110, 220, 820, 48, "Data/research: IBKR read-only, scanner, news, security master", COLOR["data"]),
            (110, 285, 820, 48, "Strategy/pool: six-layer pool, scoring, signals, intents", COLOR["runtime"]),
            (110, 350, 820, 48, "Risk/execution: paper gates, price/spread/session/position checks", COLOR["risk"]),
            (110, 415, 820, 48, "Persistence/review: SQLite, JSON, JSONL, CSV, logs, reports", COLOR["persistence"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5)]),
        ("mode9_lifecycle_flowchart.svg", "Mode 9 Runtime Lifecycle", [
            (40, 115, 130, 58, "Start", COLOR["runtime"]),
            (210, 115, 160, 58, "Lock + config", COLOR["runtime"]),
            (410, 115, 160, 58, "TWS/account sync", COLOR["external"]),
            (610, 115, 160, 58, "Pool + market data", COLOR["data"]),
            (810, 115, 160, 58, "Strategy eval", COLOR["runtime"]),
            (210, 280, 160, 58, "Risk gating", COLOR["risk"]),
            (410, 280, 160, 58, "Execution path", COLOR["execution"]),
            (610, 280, 160, 58, "Callbacks", COLOR["external"]),
            (810, 280, 160, 58, "Persist/report", COLOR["persistence"]),
            (410, 450, 160, 58, "Sleep/next cycle", COLOR["runtime"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8),(8,9),(9,1)]),
        ("market_data_sequence.svg", "Market-Data Request and Callback Sequence", [
            (55, 120, 150, 64, "Runtime", COLOR["runtime"]),
            (255, 120, 150, 64, "IBKR Readonly\\n/ Streaming", COLOR["data"]),
            (455, 120, 150, 64, "TWS Socket\\n7497", COLOR["external"]),
            (655, 120, 150, 64, "Callbacks", COLOR["external"]),
            (855, 120, 150, 64, "State Bus\\nReports", COLOR["persistence"]),
        ], [(0,1),(1,2),(2,3),(3,4)]),
        ("trading_signal_order_flow.svg", "Trading Signal and Order Flow", [
            (50, 120, 145, 58, "Candidate", COLOR["data"]),
            (230, 120, 145, 58, "Pool layer", COLOR["runtime"]),
            (410, 120, 145, 58, "Signal", COLOR["runtime"]),
            (590, 120, 145, 58, "Order intent", COLOR["execution"]),
            (770, 120, 145, 58, "Risk gate", COLOR["risk"]),
            (590, 290, 145, 58, "Paper executor", COLOR["execution"]),
            (770, 290, 145, 58, "TWS paper", COLOR["external"]),
            (410, 290, 145, 58, "Audit trail", COLOR["persistence"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)]),
        ("module_dependency_diagram.svg", "Module Communication Contract", [
            (40, 80, 160, 56, "discovery_*", COLOR["data"]),
            (250, 80, 160, 56, "pool_state.py", COLOR["runtime"]),
            (460, 80, 160, 56, "strategy_*", COLOR["runtime"]),
            (670, 80, 160, 56, "risk/session", COLOR["risk"]),
            (880, 80, 160, 56, "service/tws", COLOR["execution"]),
            (250, 250, 160, 56, "paper_audit_db", COLOR["persistence"]),
            (460, 250, 160, 56, "event_store", COLOR["persistence"]),
            (670, 250, 160, 56, "reports/logs", COLOR["persistence"]),
        ], [(0,1),(1,2),(2,3),(3,4),(1,5),(2,6),(4,7)]),
        ("six_layer_stock_pool.svg", "Six-Layer Stock Pool", [
            (90, 80, 240, 55, "MASTER_UNIVERSE", COLOR["data"]),
            (90, 155, 240, 55, "ELIGIBLE_UNIVERSE", COLOR["data"]),
            (90, 230, 240, 55, "SCAN_POOL", COLOR["runtime"]),
            (90, 305, 240, 55, "WATCH_POOL", COLOR["runtime"]),
            (90, 380, 240, 55, "SIGNAL_EXECUTION_READY_POOL", COLOR["risk"]),
            (90, 455, 240, 55, "PAPER_EXECUTION_POSITION_POOL", COLOR["execution"]),
            (500, 210, 300, 68, "Demotion/removal\\nfailed eligibility, stale quote, expired signal, rejected order", COLOR["risk"]),
            (500, 340, 300, 68, "Persistence\\ncanonical_pool_state + transition events", COLOR["persistence"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,7),(6,7)]),
        ("database_er_diagram.svg", "Database Entity Relationship Overview", [
            (70, 100, 210, 70, "cycle_snapshots", COLOR["persistence"]),
            (350, 70, 210, 70, "state_* events", COLOR["persistence"]),
            (630, 70, 210, 70, "order_intent_events", COLOR["execution"]),
            (350, 220, 210, 70, "pool_* tables", COLOR["runtime"]),
            (630, 220, 210, 70, "order_requests", COLOR["execution"]),
            (350, 370, 210, 70, "pnl/account tables", COLOR["persistence"]),
            (630, 370, 210, 70, "reports/logs refs", COLOR["review"]),
        ], [(0,1),(1,2),(2,4),(0,3),(0,5),(2,6)]),
        ("logging_observability_flowchart.svg", "Logging and Observability", [
            (60, 110, 170, 60, "Runtime events", COLOR["runtime"]),
            (290, 70, 170, 60, "SQLite rows", COLOR["persistence"]),
            (290, 180, 170, 60, "JSON/JSONL", COLOR["persistence"]),
            (520, 70, 170, 60, "Plain logs", COLOR["persistence"]),
            (520, 180, 170, 60, "Reports", COLOR["review"]),
            (750, 125, 190, 60, "End-to-end trace", COLOR["review"]),
        ], [(0,1),(0,2),(0,3),(1,5),(2,5),(3,5),(4,5)]),
        ("autonomous_review_pipeline.svg", "Autonomous Review Pipeline", [
            (35, 120, 155, 62, "SQLite/JSON\\nCSV/Logs", COLOR["persistence"]),
            (225, 120, 155, 62, "Collector", COLOR["review"]),
            (415, 120, 155, 62, "Data quality", COLOR["review"]),
            (605, 120, 155, 62, "Timeline\\nreconstruction", COLOR["review"]),
            (795, 120, 155, 62, "AI analysis", COLOR["review"]),
            (605, 300, 155, 62, "Daily/Weekly\\nIncident review", COLOR["review"]),
            (795, 300, 155, 62, "Evidence-backed\\nrecommendations", COLOR["risk"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)]),
        ("tws_disconnect_recovery.svg", "TWS Disconnect and Recovery", [
            (75, 100, 180, 58, "Callback error\\nor timeout", COLOR["external"]),
            (315, 100, 180, 58, "Mark stale\\nstate bus", COLOR["persistence"]),
            (555, 100, 180, 58, "Block execution", COLOR["risk"]),
            (795, 100, 180, 58, "Reconnect\\nreadonly/API", COLOR["external"]),
            (315, 285, 180, 58, "Resync account\\npositions/orders", COLOR["data"]),
            (555, 285, 180, 58, "Reconcile SQLite\\nand reports", COLOR["persistence"]),
            (795, 285, 180, 58, "Resume only after\\nfresh checks", COLOR["runtime"]),
        ], [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6)]),
        ("event_replay_example.svg", "End-to-End Event Replay Example", [
            (55, 100, 160, 60, "cycle_id", COLOR["runtime"]),
            (255, 100, 160, 60, "snapshot_id", COLOR["persistence"]),
            (455, 100, 160, 60, "symbol + signal", COLOR["runtime"]),
            (655, 100, 160, 60, "intent_id", COLOR["execution"]),
            (855, 100, 160, 60, "order_id/status", COLOR["execution"]),
            (255, 280, 160, 60, "SQLite rows", COLOR["persistence"]),
            (455, 280, 160, 60, "JSON reports", COLOR["persistence"]),
            (655, 280, 160, 60, "Log entries", COLOR["persistence"]),
            (855, 280, 160, 60, "Review finding", COLOR["review"]),
        ], [(0,1),(1,2),(2,3),(3,4),(1,5),(3,6),(4,7),(7,8)]),
    ]
    for name, title, nodes, edges in specs:
        write_svg(name, title, nodes, edges)
    return [{"name": name, "title": title} for name, title, _, _ in specs]


def build_pdf(facts: dict[str, Any]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Flowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents
    from reportlab.graphics.shapes import Drawing, Line, Rect, String

    font_path = Path("/Library/Fonts/Arial Unicode.ttf")
    if not font_path.exists():
        font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    pdfmetrics.registerFont(TTFont("ManualSans", str(font_path)))

    class ManualDoc(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph):
                text = flowable.getPlainText()
                style = flowable.style.name
                if style in {"Heading1", "Heading2"}:
                    key = "s" + str(abs(hash(text)))
                    self.canv.bookmarkPage(key)
                    level = 0 if style == "Heading1" else 1
                    self.canv.addOutlineEntry(text, key, level=level, closed=False)
                    self.notify("TOCEntry", (level, text, self.page, key))

    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    doc = ManualDoc(
        str(OUTPUT_PDF),
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.35 * cm,
        bottomMargin=1.25 * cm,
        title=f"IBKR Paper-Trading Engineering Manual {MANUAL_VERSION}",
        author="Codex documentation generator",
    )
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "ManualSans"
    styles["Title"].fontName = "ManualSans"
    styles["Title"].fontSize = 24
    styles["Heading1"].fontName = "ManualSans"
    styles["Heading1"].fontSize = 16
    styles["Heading1"].spaceBefore = 14
    styles["Heading1"].textColor = colors.HexColor(COLOR["ink"])
    styles["Heading2"].fontName = "ManualSans"
    styles["Heading2"].fontSize = 12.5
    styles["Heading2"].spaceBefore = 9
    styles["Heading2"].textColor = colors.HexColor("#374151")
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="ManualSans", fontSize=8.7, leading=12.2, spaceAfter=5)
    small = ParagraphStyle("Small", parent=body, fontSize=7.4, leading=9.2)
    caption = ParagraphStyle("Caption", parent=small, textColor=colors.HexColor(COLOR["muted"]), alignment=TA_CENTER)
    warning = ParagraphStyle("Warning", parent=body, borderColor=colors.HexColor(COLOR["risk"]), borderWidth=0.8, borderPadding=6, backColor=colors.HexColor("#FEF2F2"))
    cell_style = ParagraphStyle("Cell", parent=small, fontSize=5.8, leading=7.1, splitLongWords=True, wordWrap="CJK")
    header_cell_style = ParagraphStyle("HeaderCell", parent=cell_style, fontSize=6.3, leading=7.6, textColor=colors.HexColor(COLOR["ink"]))

    def p(text: str, style=body):
        return Paragraph(text, style)

    def h1(text: str):
        return Paragraph(text, styles["Heading1"])

    def h2(text: str):
        return Paragraph(text, styles["Heading2"])

    def table(rows, widths=None, font=7.0):
        local_cell = ParagraphStyle("LocalCell", parent=cell_style, fontSize=min(font, 6.4), leading=min(font, 6.4) + 1.5, splitLongWords=True, wordWrap="CJK")
        local_header = ParagraphStyle("LocalHeader", parent=header_cell_style, fontSize=min(font + 0.3, 6.7), leading=min(font + 0.3, 6.7) + 1.5, splitLongWords=True, wordWrap="CJK")
        wrapped = []
        for r, row in enumerate(rows):
            style = local_header if r == 0 else local_cell
            wrapped.append([cell if hasattr(cell, "wrap") else Paragraph(str(cell), style) for cell in row])
        t = Table(wrapped, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "ManualSans"),
            ("FONTSIZE", (0, 0), (-1, -1), font),
            ("LEADING", (0, 0), (-1, -1), font + 2),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(COLOR["ink"])),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        return t

    class Diagram(Flowable):
        def __init__(self, spec: dict[str, Any]):
            super().__init__()
            self.spec = spec
            self.width = 17.8 * cm
            self.height = 9.2 * cm

        def wrap(self, availWidth, availHeight):
            return self.width, self.height

        def draw(self):
            name = self.spec["name"]
            title = self.spec["title"]
            svg = (DIAGRAMS / name).read_text(encoding="utf-8")
            labels = []
            for part in svg.split("<text ")[2:]:
                labels.append(part.split(">", 1)[1].split("</text>", 1)[0])
            c = self.canv
            c.saveState()
            c.setStrokeColor(colors.HexColor("#CBD5E1"))
            c.setFillColor(colors.HexColor("#FFFFFF"))
            c.roundRect(0, 0, self.width, self.height, 8, fill=1)
            c.setFont("ManualSans", 11)
            c.setFillColor(colors.HexColor(COLOR["ink"]))
            c.drawString(0.35 * cm, self.height - 0.55 * cm, title)
            cols = 3
            box_w = (self.width - 1.4 * cm) / cols
            x0, y0 = 0.35 * cm, self.height - 1.55 * cm
            for i, label in enumerate(labels[:12]):
                col, row = i % cols, i // cols
                x = x0 + col * box_w
                y = y0 - row * 1.55 * cm
                color = list(COLOR.values())[i % 7]
                c.setFillColor(colors.HexColor(color), alpha=0.10)
                c.setStrokeColor(colors.HexColor(color))
                c.roundRect(x, y - 0.95 * cm, box_w - 0.22 * cm, 0.95 * cm, 5, stroke=1, fill=1)
                c.setFillColor(colors.HexColor(COLOR["ink"]))
                c.setFont("ManualSans", 7.3)
                raw_lines: list[str] = []
                for source_line in label.replace("&amp;", "&").split("\\n"):
                    words = source_line.split()
                    if not words:
                        continue
                    current = ""
                    for word in words:
                        candidate = (current + " " + word).strip()
                        if len(candidate) > 32:
                            raw_lines.append(current)
                            current = word
                        else:
                            current = candidate
                    if current:
                        raw_lines.append(current)
                for j, line in enumerate(raw_lines[:3]):
                    c.drawString(x + 0.12 * cm, y - 0.28 * cm - j * 0.22 * cm, line[:36])
                if i > 0:
                    c.setStrokeColor(colors.HexColor("#94A3B8"))
                    c.line(x - 0.15 * cm, y - 0.47 * cm, x, y - 0.47 * cm)
            c.restoreState()

    def diagram(name: str, title: str):
        return KeepTogether([Diagram({"name": name, "title": title}), Paragraph(f"Diagram: {title}. Source file: docs/manual/diagrams/{name}", caption), Spacer(1, 6)])

    def bullet(items: list[str]):
        return [p(f"• {item}") for item in items]

    story: list[Any] = []
    story.append(Spacer(1, 2.5 * cm))
    story.append(Paragraph("IBKR Paper-Trading Project", styles["Title"]))
    story.append(Paragraph("Engineering Manual / 系统工程手册", styles["Title"]))
    story.append(Spacer(1, 0.6 * cm))
    story.append(p(f"Manual version: <b>{MANUAL_VERSION}</b> | Release: <b>{RELEASE_NAME}</b> / <b>{CHINESE_NAME}</b>"))
    story.append(p(f"Status: <b>{VALIDATION_STATUS}</b>"))
    story.append(p(f"Generated: {facts['generation_date_utc']} | Git branch: {facts['git_branch']} | Git commit: {facts['git_commit']}"))
    if facts.get("git_commit_url"):
        story.append(p(f"Commit link: <a href=\"{facts['git_commit_url']}\">{facts['git_commit_url']}</a>"))
    story.append(Spacer(1, 0.5 * cm))
    story.append(p("This Foundation Baseline is a draft system architecture manual. It is repository-backed, but it is not a claim that every runtime path has been fully validated in production-like paper sessions.", warning))
    story.append(PageBreak())

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(fontName="ManualSans", name="TOCHeading1", fontSize=9.5, leftIndent=0, firstLineIndent=0, spaceBefore=4),
        ParagraphStyle(fontName="ManualSans", name="TOCHeading2", fontSize=8, leftIndent=14, firstLineIndent=0, spaceBefore=1),
    ]
    story.append(h1("Table of Contents"))
    story.append(toc)
    story.append(PageBreak())

    story.append(h1("Project Introduction"))
    story += bullet([
        "The project is an IBKR paper-trading automation and evidence system. It combines candidate discovery, market data checks, strategy decisions, risk gates, paper execution adapters, SQLite ledgers, reports, and logs.",
        "The safety boundary is paper-only. Live trading is intentionally outside the validated system boundary and must not be inferred from paper readiness.",
        "The manual is ordered System → Layers → Flows → Modules → Storage → Operations → Code Reference so a new developer can reason about architecture before reading implementation details.",
    ])
    story.append(table([
        ["Metadata", "Value"],
        ["Manual version", MANUAL_VERSION],
        ["Release", f"{RELEASE_NAME} / {CHINESE_NAME}"],
        ["Validation status", VALIDATION_STATUS],
        ["Code Git commit", facts["git_commit"]],
        ["Git branch", facts["git_branch"]],
        ["Generation date UTC", facts["generation_date_utc"]],
    ], [4.3 * cm, 12.5 * cm]))

    story.append(h1("How to Read This Manual"))
    story.append(h2("5-minute overview"))
    story += bullet([
        "Read System Overview, Layered Architecture, and the Mode 9 lifecycle diagram.",
        "Remember the invariant: candidate modules may produce facts or intents, but broker interaction must pass risk and execution gates.",
    ])
    story.append(h2("30-minute developer overview"))
    story += bullet([
        "Read flows separately: data flow, signal flow, control flow, and error flow use different arrows and evidence.",
        "Then read the module contract and six-layer pool sections before touching code.",
    ])
    story.append(h2("Deep maintenance reference"))
    story += bullet([
        "Use Database Architecture, Observability, Failure/Recovery, Developer Operations, and Source-Code Reference.",
        "Every review claim should cite runtime evidence: table row, report file, timestamp, cycle_id, order_id, or log entry.",
    ])

    story.append(h1("System Overview"))
    story.append(diagram("complete_system_mind_map.svg", "Complete system mind-map / architecture infographic"))
    story += bullet([
        "Operational boundary: the repository controls local Python services, reports, SQLite, and IBKR/TWS paper interaction through configured ports. It does not own the external TWS desktop process.",
        "Paper-only boundary: `TRADING_MODE` accepts DRY_RUN or PAPER; live trading is not an enabled mode in `trading/config.py`.",
        "External systems: IBKR TWS/IB Gateway paper socket, local filesystem, SQLite, CSV universes, generated reports, and operator-controlled scripts.",
    ])

    story.append(h1("Complete System Architecture"))
    story.append(diagram("layered_system_architecture.svg", "Layered system architecture diagram"))
    story.append(table([
        ["Layer", "Core responsibility", "Representative repository paths"],
        ["User/control", "Menus, scripts, API requests, lock state, developer commands.", "scripts/*.command, TRADING_LOCK.md, SECURITY_MODEL.md"],
        ["Runtime/scheduler", "Mode 9 cycles, duplicate-process lock, sleep cadence, status reports.", "scripts/run_autonomous_trading_agent.py, trading/process_guard.py, trading/autonomous_runtime.py"],
        ["Data/research", "Universe, scanner, news, quotes, account and position state.", "trading/ibkr_readonly.py, trading/ibkr_streaming.py, trading/news_*.py, data/*.csv"],
        ["Strategy/pool", "Candidate scoring, six-layer pool, strategy signals, buy/sell intents.", "trading/pool_state.py, trading/strategy*.py, trading/buy_decision_engine.py"],
        ["Risk", "Paper-only limits, price/spread/session/position/protection gates.", "trading/risk.py, trading/session_policy.py, trading/position_protection.py"],
        ["Execution", "Paper order construction, transmit behavior, readback, callbacks.", "trading/tws_paper.py, trading/paper_order_executor.py, trading/order_intents.py"],
        ["Audit/storage", "SQLite evidence, JSON/JSONL/CSV reports, logs.", "trading/paper_audit_db.py, trading/sqlite_event_store.py, reports/, logs/"],
    ], [3.0 * cm, 7.0 * cm, 7.0 * cm], font=6.6))

    story.append(h1("Runtime Lifecycle"))
    story.append(diagram("mode9_lifecycle_flowchart.svg", "Mode 9 lifecycle flowchart"))
    lifecycle = [
        ("Startup", "Operator/script starts the runtime; config is read from environment and local files."),
        ("Duplicate-instance lock", "`trading/process_guard.py` records/validates the execution-writer owner."),
        ("Configuration validation", "`Settings.load` constrains mode to DRY_RUN/PAPER and loads limits, tokens, ports, symbols, and audit DB."),
        ("IBKR connection", "Read-only or paper adapters connect to configured localhost TWS paper port when invoked by runtime diagnostics or execution path."),
        ("Account/position synchronization", "Account, position, PnL, open orders, and quote states are refreshed into reports/state buses."),
        ("Pool loading", "Security master and pool membership evidence feed the canonical six-layer pool."),
        ("Market-data acquisition", "Readonly, streaming, or report-cache data are used depending on session and capability."),
        ("Strategy evaluation", "Strategy modules create signals and intents; they do not directly call IBKR."),
        ("Risk gating", "Session, quote freshness, spread, price, order value, position, and protection gates must pass."),
        ("Execution", "Only paper execution adapters may submit orders; report-only modules emit evidence only."),
        ("Callbacks", "IBKR callbacks update buses, errors, commissions, order status, and stale/connection state."),
        ("Persistence/reporting", "SQLite rows, JSON reports, JSONL events, CSVs, and logs are written."),
        ("Sleep/next cycle", "Runtime sleeps according to configured cadence and repeats."),
        ("Shutdown/recovery", "State is reconstructed from reports/SQLite; stale or inconsistent state blocks execution."),
    ]
    story.append(table([["Stage", "Repository-backed behavior"]] + lifecycle, [4.2 * cm, 12.5 * cm], font=6.8))

    story.append(h1("Data Flow, Signal Flow, Control Flow, and Error Flow"))
    story.append(diagram("market_data_sequence.svg", "Market-data request and callback sequence diagram"))
    story.append(diagram("trading_signal_order_flow.svg", "Trading-signal and order-execution flowchart"))
    story += bullet([
        "Data flow is blue: external/reference data, quotes, account state, positions, news, scanner output, and CSV universes move into buses, reports, and SQLite.",
        "Signal flow is green: candidate scoring and strategy modules promote symbols through pool layers, then emit strategy_signals or order_intent_events.",
        "Control flow is orange: operator commands, API endpoints, lock/token state, and transmit flags decide whether a request may advance toward TWS.",
        "Error flow is red/purple: exceptions, stale states, callback errors, rejections, and blocked reasons are persisted and should stop execution before review.",
    ])

    story.append(h1("Module Communication Contract"))
    story.append(diagram("module_dependency_diagram.svg", "Module communication/dependency diagram"))
    module_rows = [
        ["Module/group", "Responsibility", "Inputs", "Outputs", "Forbidden direct dependency"],
        ["Discovery/scanner/news", "Find and structure candidate evidence.", "CSV universes, scanner/news providers, reports.", "discovery_candidates, raw/structured news, source status.", "Must not submit broker orders."],
        ["Pool state/manager", "Own canonical six-layer stock state and transitions.", "Discovery, eligibility, quotes, signals, order callbacks.", "canonical_pool_state, transition events, pool reports.", "Must not bypass risk/execution gates."],
        ["Strategy modules", "Evaluate positions/candidates and emit decisions.", "Pool membership, quotes, bars, account state.", "strategy_signals, buy/sell decisions, intents.", "Must not call TWS directly."],
        ["Risk/session/position gates", "Approve, block, or require review.", "Intent, session, quote, account, position, config.", "blocked_reason, readiness reports, risk events.", "Must not mutate broker state except via approved execution path."],
        ["Execution adapters", "Construct paper orders and handle TWS acknowledgements.", "Approved proposal/intents, settings, TWS client.", "order_requests, order status, readback evidence.", "Must not enable live mode."],
        ["Audit/reporting", "Persist runtime evidence and review artifacts.", "Events, reports, callbacks, decisions.", "SQLite, JSON, JSONL, CSV, logs.", "Must not make trading decisions by itself."],
    ]
    story.append(table(module_rows, [3.0 * cm, 4.0 * cm, 3.3 * cm, 3.5 * cm, 3.4 * cm], font=6.2))

    story.append(h1("Six-Layer Stock Pool"))
    story.append(diagram("six_layer_stock_pool.svg", "Six-layer stock-pool diagram"))
    layer_rows = [["Layer", "Purpose", "Promotion", "Removal/demotion", "Capacity/refresh"]]
    layer_notes = {
        "MASTER_UNIVERSE": ("Global security master.", "Symbol discovered or manually seeded.", "Disabled, unsupported type/currency.", "Capacity is file/report/db bounded; refreshed by security master and pool builders."),
        "ELIGIBLE_UNIVERSE": ("Hard eligibility passed.", "Contract resolved, market data available, price/liquidity checks pass.", "Eligibility failure or explicit block.", "Refreshed by eligibility evaluation."),
        "SCAN_POOL": ("Coarse strategy/scanner nomination.", "Strategy/source nominates with score and TTL.", "TTL expiry or lower-quality evidence.", "TTL configured by call site; records in transition events."),
        "WATCH_POOL": ("Quote-ready active monitoring.", "Fresh quote and spread check pass.", "Stale quote, spread failure, TTL expiry.", "Refresh follows monitoring and quote freshness policy."),
        "SIGNAL_EXECUTION_READY_POOL": ("Signal is execution-ready but not yet a position.", "Signal passes score, event/risk readiness, and duplicate-order checks.", "Expired signal, active order conflict, risk failure.", "Bound by strategy and order gating."),
        "PAPER_EXECUTION_POSITION_POOL": ("Paper position/order lifecycle under monitoring.", "Order accepted/filled or position open.", "Closed, rejected, expired, or reconciled out.", "Refreshed by callbacks, open orders, positions, and reports."),
    }
    for layer in facts["pool_layers"]:
        layer_rows.append([layer, *layer_notes.get(layer, ("Repository layer.", "See pool_state.py.", "See pool_state.py.", "See reports."))])
    story.append(table(layer_rows, [3.5 * cm, 3.1 * cm, 3.4 * cm, 3.6 * cm, 3.2 * cm], font=5.9))

    story.append(h1("IBKR/TWS Integration"))
    story += bullet([
        "Python entry points use IBKR adapters such as `trading/tws_paper.py`, `trading/ibkr_readonly.py`, `trading/ibkr_streaming.py`, and callback bridge/audit modules.",
        "Socket/API connection defaults are loaded from environment: TWS host `127.0.0.1`, paper port `7497`, and client IDs from `trading/config.py`.",
        "Request path: service validates proposal, reserves audit idempotency key, constructs order, submits to paper adapter only after gates pass.",
        "Callback path: TWS callbacks update order status, errors, account/position/quote buses, and generated reports.",
        "Reconnection and reconciliation depend on stale-state detection, readback, account/open-order refresh, and SQLite/report evidence.",
    ])

    story.append(h1("Risk and Execution Architecture"))
    story += bullet([
        "Paper-only restrictions: `Settings.load` accepts only DRY_RUN or PAPER. Live order submission is intentionally absent from the validated mode set.",
        "BUY/live/options gates: reports show paper-only and report-only flags; options execution forbids live options and naked/market option strategies.",
        "Price/spread/session validation: price normalizer, session policy, quote readiness, spread checks, market session reports, and market quote crosscheck all contribute blockers.",
        "Position protection: protective sell, gap escape, profit lock/take profit/trailing profit, and lot protection are tracked separately from new BUY logic.",
        "Order construction and transmit behavior live in `trading/tws_paper.py`; staged orders use `transmit=False`, paper submission uses explicit transmit behavior after gates.",
        "Rejection handling writes blocked reasons, IBKR errors, readback status, and audit rows so review can reconstruct the failed path.",
    ])

    story.append(h1("Database Architecture"))
    story.append(diagram("database_er_diagram.svg", "Database entity relationship diagram"))
    story.append(p(f"SQLite database inspected: {facts['sqlite_database']}. Table count at generation: {facts['sqlite_table_count']}."))
    db_rows = [["Table", "Rows", "Primary key", "Purpose", "Writer / readers"]]
    for info in facts["sqlite_tables"][:42]:
        db_rows.append([info["name"], str(info["row_count"]), info["primary_key"], info["purpose"], f"{info['writer']} / {info['readers']}"])
    story.append(table(db_rows, [3.0 * cm, 1.2 * cm, 3.0 * cm, 4.7 * cm, 4.9 * cm], font=5.55))
    story.append(p("Additional table schemas and counts are preserved in `docs/manual/generated/manual_facts.json`; diagnostic SQL is in `docs/manual/queries/database_diagnostics.sql`.", small))

    story.append(h1("Log and Observability Architecture"))
    story.append(diagram("logging_observability_flowchart.svg", "Logging and observability flowchart"))
    story += bullet([
        "Log categories include API logs, autonomous agent logs, launchd logs, scheduler logs, market-data audit logs, and report-builder logs.",
        "Structured evidence is primarily SQLite, JSON, JSONL, and CSV; plain-text logs are used for process/system output and failures.",
        "Correlation fields include cycle_id, discovery_run_id, snapshot_id, intent_id, order_id, event_id, symbol, timestamps, and report_path.",
        "Timestamps are mostly UTC ISO strings in generated evidence; local operational docs mention Europe/Berlin where daily limits or operator context require it.",
    ])
    obs_rows = [["Artifact", "Inspection role"]]
    for record in facts["report_inventory"][:28]:
        obs_rows.append([record["path"], ", ".join(record.get("keys", [])) or f"size={record.get('size', 0)} bytes"])
    story.append(table(obs_rows, [7.0 * cm, 9.7 * cm], font=6.2))

    story.append(h1("Autonomous Review Framework"))
    story.append(diagram("autonomous_review_pipeline.svg", "Autonomous Review pipeline diagram"))
    story += bullet([
        "The AI review pipeline must prioritize generated runtime evidence over source-code assumptions.",
        "Daily review: summarize cycles, blockers, stale data, submitted/blocked orders, and account/PnL changes.",
        "Weekly review: compare candidate quality, pool transitions, risk blocks, execution quality, and performance attribution.",
        "Incident review: reconstruct a timeline from SQLite rows, reports, JSONL events, logs, callbacks, and TWS readback.",
        "Strategy/risk/execution/performance/data-quality reviews must cite row/table/file/timestamp/cycle_id/order_id/log evidence.",
    ])

    story.append(h1("Failure and Recovery Scenarios"))
    story.append(diagram("tws_disconnect_recovery.svg", "TWS disconnect and recovery flowchart"))
    failures = [
        ["Scenario", "Expected propagation", "Recovery evidence"],
        ["TWS disconnected", "Callback/socket error, stale state, execution blocked.", "ibkr_error_events, position_guard/latest.json, logs."],
        ["Stale market data", "Quote readiness false, spread/quote gates block execution.", "quote_state_events, market_quote_crosscheck_events."],
        ["Missing bid/ask", "Market session crosscheck determines whether normal closed-market condition or feed problem.", "market_session/latest.json, market_quote_crosscheck/latest.json."],
        ["Market closed", "Session policy disables auto trade or blocks readiness.", "market_session_events, paper_order_readiness_events."],
        ["Duplicate process", "Process guard reports duplicate PIDs or accepted lock owner.", "reports/process_guard/latest.json, .runtime lock."],
        ["Database locked", "SQLite writer exception should fail current evidence write and be visible in logs.", "plain logs plus missing/partial row checks."],
        ["Callback timeout", "State remains stale and execution is blocked.", "subscription_state_events, callback_wiring_events."],
        ["Rejected order", "Rejected status/IBKR error written, order readback not accepted.", "order_requests, ibkr_error_events, order_readback_events."],
        ["Partial execution", "Execution state and order status indicate partial fill; position/PnL reconciliation required.", "execution_state_events, position_pnl_snapshots."],
        ["Inconsistent account state", "Freshness and reconciliation checks block execution.", "account_state/latest.json, realtime_account_state_bus/latest.json."],
        ["Restart after crash", "Recover from SQLite/reports/open order readback before resuming.", "cycle_snapshots, open_order_state_events, process_guard."],
    ]
    story.append(table(failures, [3.4 * cm, 6.4 * cm, 6.8 * cm], font=6.1))
    story.append(diagram("event_replay_example.svg", "End-to-end event replay example"))

    story.append(h1("Developer Operations"))
    story += bullet([
        "Start/stop: use documented command scripts and runbooks; avoid direct runtime entry unless you understand the lock/token state.",
        "Confirm single runtime: inspect `reports/process_guard/latest.json` and `.runtime/execution_writer.lock`.",
        "Inspect current state: read `reports/account_state/latest.json`, `reports/realtime_account_state_bus/latest.json`, and `reports/mode9_infrastructure_status/latest.json`.",
        "Inspect SQLite: run read-only `sqlite3 trading_audit.sqlite3` queries from `docs/manual/queries/database_diagnostics.sql`.",
        "Inspect logs: start with `logs/trading_api.log`, `logs/autonomous_agent.log`, and launchd logs.",
        "Generate review: collect SQLite rows, reports, JSONL events, CSVs, and logs; require citations for every AI conclusion.",
        "Verify no live trading: check `TRADING_MODE`, `live_trading_enabled` report fields, `TRADING_LOCK.md`, and `SECURITY_MODEL.md`.",
    ])

    story.append(h1("Source-Code Reference"))
    story.append(p("This section intentionally appears after the architecture sections. It preserves the file-level view while keeping system behavior first. Paths are repository-relative and were extracted from real files."))
    ref_rows = [["Path", "Purpose", "Classes", "Functions"]]
    for ref in facts["source_reference"][:120]:
        ref_rows.append([ref["path"], ref["purpose"], ref["classes"], ref["functions"]])
    story.append(table(ref_rows, [4.5 * cm, 5.3 * cm, 3.2 * cm, 3.8 * cm], font=4.9))

    story.append(h1("Appendix"))
    story.append(h2("Glossary"))
    story.append(table([
        ["Term", "Meaning"],
        ["Mode 9", "Autonomous agent background mode described by project docs and reports."],
        ["Paper-only", "Execution is limited to IBKR paper-trading environment; live mode is not validated."],
        ["cycle_id", "Runtime cycle correlation key used across SQLite, reports, and review timelines."],
        ["snapshot_id", "Immutable state snapshot reference for a decision cycle."],
        ["intent_id", "Structured order intent identifier; not necessarily a submitted order."],
    ], [4.0 * cm, 12.5 * cm], font=6.8))
    story.append(h2("Configuration Reference"))
    story += bullet([
        "`TRADING_MODE`: DRY_RUN or PAPER.",
        "`ALLOW_TWS_STAGING`, `ALLOW_PAPER_TRANSMIT`, `ALLOW_OUTSIDE_RTH`, `TRADING_KILL_SWITCH`: major safety switches.",
        "`TWS_HOST`, `TWS_PORT`, `TWS_CLIENT_ID`: TWS API connection values.",
        "`AUDIT_DB`: defaults to `trading_audit.sqlite3`.",
        "`MAX_QUANTITY`, `MAX_ORDER_VALUE`, `MAX_RISK_PER_ORDER`, `MAX_DAILY_NOTIONAL_VALUE`: risk limits.",
    ])
    story.append(h2("Facts Requiring Manual Confirmation"))
    story += bullet(facts["manual_confirmation_required"])
    story.append(h2("Data Inventory"))
    story.append(table([["Path", "Size", "Rows", "Columns"]] + [[r["path"], str(r["size_bytes"]), str(r.get("row_count_without_header", "")), ", ".join(r.get("columns", [])[:8])] for r in facts["data_inventory"]], [4.4 * cm, 2.3 * cm, 2.0 * cm, 8.0 * cm], font=6.2))
    story.append(h2("Git/Version Information"))
    story.append(table([
        ["Field", "Value"],
        ["Manual version", MANUAL_VERSION],
        ["Release name", RELEASE_NAME],
        ["Chinese name", CHINESE_NAME],
        ["Git branch", facts["git_branch"]],
        ["Git commit", facts["git_commit"]],
        ["Git remote", facts["git_remote"]],
        ["Commit URL", facts.get("git_commit_url", "")],
        ["Dirty worktree at generation", "yes" if facts.get("git_status_short") else "no"],
    ], [4.2 * cm, 12.5 * cm], font=6.7))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("ManualSans", 7)
        canvas.setFillColor(colors.HexColor(COLOR["muted"]))
        canvas.drawString(1.35 * cm, 0.65 * cm, f"{MANUAL_VERSION} Foundation Baseline | Draft system architecture manual")
        canvas.drawRightString(A4[0] - 1.35 * cm, 0.65 * cm, f"Page {doc.page}")
        canvas.restoreState()

    doc.multiBuild(story, onFirstPage=on_page, onLaterPages=on_page)


def main() -> int:
    facts = collect_facts()
    diagrams = build_diagrams()
    facts["diagrams"] = diagrams
    FACTS_PATH.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")
    build_pdf(facts)
    print(json.dumps({"pdf": str(OUTPUT_PDF), "facts": str(FACTS_PATH), "diagrams": len(diagrams)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
