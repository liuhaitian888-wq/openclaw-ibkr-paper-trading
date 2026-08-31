#!/usr/bin/env python3
"""Validate the generated Foundation Baseline engineering manual."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANUAL_ROOT = ROOT / "docs" / "manual"
FACTS_PATH = MANUAL_ROOT / "generated" / "manual_facts.json"
REPORT_PATH = MANUAL_ROOT / "generated" / "manual_validation.json"
PDF_PATH = ROOT / "output" / "pdf" / "ibkr_paper_trading_engineering_manual_v0.1.0_cn.pdf"

REQUIRED_CHAPTERS = [
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

REQUIRED_DIAGRAMS = [
    "complete_system_mind_map.svg",
    "layered_system_architecture.svg",
    "mode9_lifecycle_flowchart.svg",
    "market_data_sequence.svg",
    "trading_signal_order_flow.svg",
    "module_dependency_diagram.svg",
    "six_layer_stock_pool.svg",
    "database_er_diagram.svg",
    "logging_observability_flowchart.svg",
    "autonomous_review_pipeline.svg",
    "tws_disconnect_recovery.svg",
    "event_replay_example.svg",
]


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not FACTS_PATH.exists():
        errors.append(f"missing facts file: {FACTS_PATH}")
        facts = {}
    else:
        facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))

    chapters = facts.get("chapters", [])
    for chapter in REQUIRED_CHAPTERS:
        if chapter not in chapters:
            errors.append(f"missing required chapter: {chapter}")

    for name in REQUIRED_DIAGRAMS:
        path = MANUAL_ROOT / "diagrams" / name
        if not path.exists():
            errors.append(f"missing required diagram: {path}")
        elif "<svg" not in path.read_text(encoding="utf-8", errors="ignore")[:500]:
            errors.append(f"diagram is not SVG: {path}")

    for key in ["manual_version", "release_name", "chinese_name", "git_commit", "git_branch", "generation_date_utc", "validation_status"]:
        if not facts.get(key):
            errors.append(f"missing baseline metadata: {key}")

    if facts.get("manual_version") != "v0.1.0":
        errors.append("manual_version must remain v0.1.0 for Foundation Baseline")
    if "v1.0" in json.dumps(facts) or "v2.0" in json.dumps(facts):
        errors.append("found prohibited v1.0/v2.0 wording in generated facts")

    for rel in facts.get("repository_paths", []):
        if not (ROOT / rel).exists():
            errors.append(f"repository path does not exist: {rel}")

    db_path = ROOT / "trading_audit.sqlite3"
    if not db_path.exists():
        errors.append("missing trading_audit.sqlite3")
    else:
        try:
            with sqlite3.connect(db_path) as con:
                tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                quick = con.execute("PRAGMA quick_check").fetchall()
            if not tables:
                errors.append("SQLite database has no tables")
            if quick and quick[0][0] != "ok":
                warnings.append(f"SQLite quick_check returned: {quick[0][0]}")
        except sqlite3.DatabaseError as exc:
            warnings.append(f"SQLite schema partially readable but health check failed: {exc}")

    if not PDF_PATH.exists():
        errors.append(f"missing generated PDF: {PDF_PATH}")
    else:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(PDF_PATH))
            page_count = len(reader.pages)
            if page_count < 10:
                errors.append(f"PDF page count unexpectedly low: {page_count}")
            outlines = getattr(reader, "outline", []) or []
            if not outlines:
                warnings.append("PDF has no readable outline from pypdf")
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
            placeholders = ["TODO", "TBD", "PAGE XX", "??"]
            if any(marker in text for marker in placeholders):
                errors.append("PDF contains unresolved placeholder text in early pages")
        except Exception as exc:  # pragma: no cover - dependency/environment guard
            warnings.append(f"PDF inspection failed: {exc}")

    report = {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "pdf_path": str(PDF_PATH),
        "facts_path": str(FACTS_PATH),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
