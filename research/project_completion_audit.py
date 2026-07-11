import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class CompletionRequirement:
    name: str
    status: str
    evidence: str
    detail: str
    required_to_complete_goal: bool = True


@dataclass(frozen=True)
class ProjectCompletionAudit:
    source: str
    created_at: str
    status: str
    summary: str
    requirements: list[CompletionRequirement] = field(default_factory=list)
    next_required_evidence: list[str] = field(default_factory=list)


def build_completion_audit(
    *,
    strategy_catalog: Optional[Mapping[str, Any]],
    preflight: Optional[Mapping[str, Any]],
    evidence_bundle: Optional[Mapping[str, Any]],
    readiness_monitor: Optional[Mapping[str, Any]],
    rehearsal: Optional[Mapping[str, Any]],
    full_pipeline: Optional[Mapping[str, Any]] = None,
    quote_quality: Optional[Mapping[str, Any]] = None,
    paper_plan: Optional[Mapping[str, Any]] = None,
    readiness: Optional[Mapping[str, Any]] = None,
    execution_gate: Optional[Mapping[str, Any]] = None,
) -> ProjectCompletionAudit:
    requirements = [
        _requirement(
            "book_methodology_mapped_to_modules",
            strategy_catalog is not None and strategy_catalog.get("status") == "modular_catalog_ready",
            "reports/strategy_catalog.json",
            f"strategy catalog status={_status(strategy_catalog)}",
        ),
        _requirement(
            "safe_simulated_ready_rehearsal",
            _clean_rehearsal(rehearsal),
            "reports/paper_trial_rehearsal/paper_trial_rehearsal.json",
            _rehearsal_detail(rehearsal),
        ),
        _requirement(
            "real_ibkr_window_ready",
            preflight is not None and preflight.get("status") == "ready_for_validate_only_window",
            "reports/paper_trial_preflight_checklist.json",
            f"preflight status={_status(preflight)}; next_allowed_action={_value(preflight, 'next_allowed_action')}",
        ),
        _requirement(
            "trading_api_and_tws_health_confirmed",
            readiness_monitor is not None and readiness_monitor.get("status") == "ready_for_validate_only_window",
            "reports/paper_trial_readiness_monitor.json",
            f"readiness monitor status={_status(readiness_monitor)}",
        ),
        _requirement(
            "real_ibkr_quote_capture_done",
            _quote_capture_done(evidence_bundle, full_pipeline),
            "reports/ibkr_quote_recorder.json",
            f"evidence stage={_stage(evidence_bundle)}; quote_rows_written={_value(full_pipeline, 'quote_rows_written')}",
        ),
        _requirement(
            "validate_only_results_done",
            _validate_done(evidence_bundle, full_pipeline, paper_plan, readiness),
            "reports/paper_validation_plan.json",
            _validate_detail(evidence_bundle, full_pipeline, paper_plan, readiness, execution_gate, quote_quality),
        ),
        _requirement(
            "one_share_paper_order_reconciled",
            _stage(evidence_bundle) == "paper_reconciled",
            "reports/paper_trial_evidence_bundle.json",
            f"evidence stage={_stage(evidence_bundle)}",
        ),
    ]
    incomplete = [item for item in requirements if item.required_to_complete_goal and item.status != "complete"]
    status = "complete" if not incomplete else "incomplete_real_ibkr_evidence_missing"
    return ProjectCompletionAudit(
        source="project_completion_audit",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        summary=_summary(status, incomplete),
        requirements=requirements,
        next_required_evidence=_next_required_evidence(incomplete),
    )


def write_completion_audit_json(audit: ProjectCompletionAudit, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(audit), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_completion_audit_markdown(audit: ProjectCompletionAudit, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(audit), encoding="utf-8")
    return output


def render_markdown(audit: ProjectCompletionAudit) -> str:
    lines = [
        "# Project Completion Audit",
        "",
        f"Generated: `{audit.created_at}`",
        "",
        f"Status: `{audit.status}`",
        "",
        audit.summary,
        "",
        "## Requirements",
        "",
    ]
    for item in audit.requirements:
        lines.extend(
            [
                f"### {item.name}",
                "",
                f"- Status: `{item.status}`",
                f"- Required: `{str(item.required_to_complete_goal).lower()}`",
                f"- Evidence: `{item.evidence}`",
                f"- Detail: {item.detail}",
                "",
            ]
        )
    lines.extend(["## Next Required Evidence", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(audit.next_required_evidence, start=1))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether the current project evidence proves the real IBKR paper goal complete.")
    parser.add_argument("--strategy-catalog", type=Path, default=PROJECT_ROOT / "reports" / "strategy_catalog.json")
    parser.add_argument("--preflight", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.json")
    parser.add_argument("--evidence-bundle", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_evidence_bundle.json")
    parser.add_argument("--readiness-monitor", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_readiness_monitor.json")
    parser.add_argument("--rehearsal", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_rehearsal" / "paper_trial_rehearsal.json")
    parser.add_argument("--full-pipeline", type=Path, default=PROJECT_ROOT / "reports" / "full_paper_trial_pipeline.json")
    parser.add_argument("--quote-quality", type=Path, default=PROJECT_ROOT / "reports" / "quote_quality_report.json")
    parser.add_argument("--paper-plan", type=Path, default=PROJECT_ROOT / "reports" / "paper_validation_plan.json")
    parser.add_argument("--readiness-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_readiness_report.json")
    parser.add_argument("--execution-gate", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "project_completion_audit.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "project_completion_audit.md")
    args = parser.parse_args()

    audit = build_completion_audit(
        strategy_catalog=_load_optional_json(args.strategy_catalog),
        preflight=_load_optional_json(args.preflight),
        evidence_bundle=_load_optional_json(args.evidence_bundle),
        readiness_monitor=_load_optional_json(args.readiness_monitor),
        rehearsal=_load_optional_json(args.rehearsal),
        full_pipeline=_load_optional_json(args.full_pipeline),
        quote_quality=_load_optional_json(args.quote_quality),
        paper_plan=_load_optional_json(args.paper_plan),
        readiness=_load_optional_json(args.readiness_report),
        execution_gate=_load_optional_json(args.execution_gate),
    )
    write_completion_audit_json(audit, args.output_json)
    write_completion_audit_markdown(audit, args.output_md)
    print(json.dumps(asdict(audit), indent=2, sort_keys=True))
    return 0


def _requirement(name: str, condition: bool, evidence: str, detail: str) -> CompletionRequirement:
    return CompletionRequirement(
        name=name,
        status="complete" if condition else "incomplete",
        evidence=evidence,
        detail=detail,
    )


def _summary(status: str, incomplete: list[CompletionRequirement]) -> str:
    if status == "complete":
        return "All required evidence is present for the current objective."
    missing = ", ".join(item.name for item in incomplete)
    return f"The project is not complete because required evidence is missing or incomplete: {missing}."


def _next_required_evidence(incomplete: list[CompletionRequirement]) -> list[str]:
    mapping = {
        "real_ibkr_window_ready": "Start TWS/IB Gateway paper, TRADE_LOCK, token, and rerun the preflight checklist until it reaches ready_for_validate_only_window.",
        "trading_api_and_tws_health_confirmed": "Run monitor_paper_trial_readiness.py until /health reports ready TWS paper state.",
        "real_ibkr_quote_capture_done": "Run the guarded session after preflight readiness so IBKR quote capture and diagnostics are recorded.",
        "validate_only_results_done": "Collect a real IBKR sample that produces at least one validate payload, then run guarded validate-only and inspect validation/readiness/execution-gate reports.",
        "one_share_paper_order_reconciled": "Submit one explicit PAPER_ONLY_1_SHARE paper order only after validation, then reconcile TWS, audit, and P&L readbacks.",
    }
    return [mapping.get(item.name, f"Provide stronger evidence for {item.name}.") for item in incomplete]


def _clean_rehearsal(payload: Optional[Mapping[str, Any]]) -> bool:
    if payload is None:
        return False
    return (
        payload.get("status") == "completed"
        and payload.get("ibkr_market_data_used") is False
        and payload.get("trading_api_validate_used") is False
        and payload.get("paper_order_used") is False
    )


def _rehearsal_detail(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "rehearsal report is missing"
    return (
        f"status={payload.get('status')}; "
        f"ibkr_market_data_used={payload.get('ibkr_market_data_used')}; "
        f"trading_api_validate_used={payload.get('trading_api_validate_used')}; "
        f"paper_order_used={payload.get('paper_order_used')}"
    )


def _stage(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "missing"
    return str(payload.get("stage", payload.get("status", "present")))


def _quote_capture_done(evidence_bundle: Optional[Mapping[str, Any]], full_pipeline: Optional[Mapping[str, Any]]) -> bool:
    if _stage(evidence_bundle) in {"blocked_before_paper_window", "missing"}:
        return False
    try:
        return int(full_pipeline.get("quote_rows_written", 0)) > 0 if full_pipeline is not None else True
    except (TypeError, ValueError):
        return False


def _validate_done(
    evidence_bundle: Optional[Mapping[str, Any]],
    full_pipeline: Optional[Mapping[str, Any]],
    paper_plan: Optional[Mapping[str, Any]] = None,
    readiness: Optional[Mapping[str, Any]] = None,
) -> bool:
    if _stage(evidence_bundle) in {"ready_for_explicit_paper_submit", "paper_submitted_needs_reconciliation", "paper_reconciled"}:
        return True
    if paper_plan is not None and readiness is not None:
        try:
            return (
                int(paper_plan.get("validate_payload_count", 0)) > 0
                and int(readiness.get("validate_approved_count", 0)) > 0
            )
        except (TypeError, ValueError):
            return False
    if full_pipeline is None:
        return False
    try:
        return full_pipeline.get("submitted_validate") is True and int(full_pipeline.get("validate_payload_count", 0)) > 0
    except (TypeError, ValueError):
        return False


def _validate_detail(
    evidence_bundle: Optional[Mapping[str, Any]],
    full_pipeline: Optional[Mapping[str, Any]],
    paper_plan: Optional[Mapping[str, Any]],
    readiness: Optional[Mapping[str, Any]],
    execution_gate: Optional[Mapping[str, Any]],
    quote_quality: Optional[Mapping[str, Any]],
) -> str:
    current_payload_count = _value(paper_plan, "validate_payload_count")
    if current_payload_count == "missing":
        current_payload_count = _value(full_pipeline, "validate_payload_count")
    return (
        f"evidence stage={_stage(evidence_bundle)}; "
        f"plan_source={_value(paper_plan, 'source')}; "
        f"validate_payload_count={current_payload_count}; "
        f"readiness_status={_status(readiness)}; "
        f"validate_approved_count={_value(readiness, 'validate_approved_count')}; "
        f"execution_gate_status={_status(execution_gate)}; "
        f"legacy_full_pipeline_payload_count={_value(full_pipeline, 'validate_payload_count')}; "
        f"quote_quality_status={_status(quote_quality)}"
    )


def _status(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "missing"
    return str(payload.get("status", "present"))


def _value(payload: Optional[Mapping[str, Any]], key: str) -> str:
    if payload is None:
        return "missing"
    return str(payload.get(key, "missing"))


def _load_optional_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
