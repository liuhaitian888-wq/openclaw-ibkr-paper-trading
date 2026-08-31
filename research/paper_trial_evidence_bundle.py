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
class EvidenceArtifact:
    name: str
    path: str
    exists: bool
    status: str
    created_at: str = ""


@dataclass(frozen=True)
class PaperTrialEvidenceBundle:
    source: str
    created_at: str
    stage: str
    summary: str
    statuses: dict[str, str]
    next_actions: list[str] = field(default_factory=list)
    artifacts: list[EvidenceArtifact] = field(default_factory=list)


def build_evidence_bundle(
    *,
    audit: Optional[Mapping[str, Any]],
    guarded_session: Optional[Mapping[str, Any]],
    runbook: Optional[Mapping[str, Any]],
    reconciliation: Optional[Mapping[str, Any]],
    artifact_paths: Mapping[str, Path],
    readiness: Optional[Mapping[str, Any]] = None,
    execution_gate: Optional[Mapping[str, Any]] = None,
) -> PaperTrialEvidenceBundle:
    statuses = {
        "environment": _status(audit),
        "guarded_session": _status(guarded_session),
        "readiness": _status(readiness),
        "execution_gate": _status(execution_gate),
        "runbook": _status(runbook),
        "reconciliation": _status(reconciliation),
    }
    stage = _stage(statuses)
    return PaperTrialEvidenceBundle(
        source="paper_trial_evidence_bundle",
        created_at=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        summary=_summary(stage),
        statuses=statuses,
        next_actions=_next_actions(stage, audit, runbook),
        artifacts=_artifacts(artifact_paths),
    )


def write_evidence_bundle(bundle: PaperTrialEvidenceBundle, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(bundle), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_evidence_markdown(bundle: PaperTrialEvidenceBundle, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Paper Trial Evidence Bundle",
        "",
        f"Generated: `{bundle.created_at}`",
        "",
        f"Stage: `{bundle.stage}`",
        "",
        bundle.summary,
        "",
        "## Statuses",
        "",
    ]
    lines.extend(f"- `{name}`: `{status}`" for name, status in sorted(bundle.statuses.items()))
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"{index}. {action}" for index, action in enumerate(bundle.next_actions, start=1))
    lines.extend(["", "## Artifacts", ""])
    for artifact in bundle.artifacts:
        marker = "present" if artifact.exists else "missing"
        created = f"; created_at={artifact.created_at}" if artifact.created_at else ""
        lines.append(f"- `{artifact.name}`: `{marker}`; status=`{artifact.status}`; path=`{artifact.path}`{created}")
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a single current-state evidence bundle for the paper trial workflow.")
    parser.add_argument("--audit-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_environment_audit.json")
    parser.add_argument("--guarded-session-report", type=Path, default=PROJECT_ROOT / "reports" / "guarded_paper_trial_session.json")
    parser.add_argument("--runbook-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_runbook.json")
    parser.add_argument("--readiness-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_readiness_report.json")
    parser.add_argument("--execution-gate-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--pre-submit-review", type=Path, default=PROJECT_ROOT / "reports" / "paper_pre_submit_review.json")
    parser.add_argument("--reconciliation-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_reconciliation.json")
    parser.add_argument("--status-html", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_status.html")
    parser.add_argument("--preflight-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.json")
    parser.add_argument("--quote-quality-json", type=Path, default=PROJECT_ROOT / "reports" / "quote_quality_report.json")
    parser.add_argument("--candidate-hunt-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_candidate_hunt.json")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_evidence_bundle.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_evidence_bundle.md")
    args = parser.parse_args()

    artifact_paths = {
        "environment_audit": args.audit_report,
        "guarded_session": args.guarded_session_report,
        "runbook_json": args.runbook_json,
        "readiness_report": args.readiness_report,
        "execution_gate": args.execution_gate_report,
        "pre_submit_review": args.pre_submit_review,
        "reconciliation": args.reconciliation_report,
        "status_html": args.status_html,
        "preflight_json": args.preflight_json,
        "quote_quality_json": args.quote_quality_json,
        "candidate_hunt_json": args.candidate_hunt_json,
    }
    bundle = build_evidence_bundle(
        audit=_load_optional_json(args.audit_report),
        guarded_session=_load_optional_json(args.guarded_session_report),
        runbook=_load_optional_json(args.runbook_json),
        readiness=_load_optional_json(args.readiness_report),
        execution_gate=_load_optional_json(args.execution_gate_report),
        reconciliation=_load_optional_json(args.reconciliation_report),
        artifact_paths=artifact_paths,
    )
    write_evidence_bundle(bundle, args.output_json)
    write_evidence_markdown(bundle, args.output_md)
    print(json.dumps(asdict(bundle), indent=2, sort_keys=True))
    return 0


def _stage(statuses: Mapping[str, str]) -> str:
    environment = statuses.get("environment", "missing")
    guarded = statuses.get("guarded_session", "missing")
    readiness = statuses.get("readiness", "missing")
    execution_gate = statuses.get("execution_gate", "missing")
    reconciliation = statuses.get("reconciliation", "missing")
    if environment != "ready_for_one_share_paper_trial":
        return "blocked_before_paper_window"
    if reconciliation == "reconciled":
        return "paper_reconciled"
    if execution_gate == "submitted":
        return "paper_submitted_needs_reconciliation"
    if execution_gate == "ready_for_explicit_paper_submit":
        return "ready_for_explicit_paper_submit"
    if readiness == "validate_required":
        return "validate_required"
    if guarded == "paper_submitted":
        if reconciliation == "reconciled":
            return "paper_reconciled"
        return "paper_submitted_needs_reconciliation"
    if guarded in {"ready_for_explicit_paper_submit", "validate_required"}:
        return guarded
    if environment == "ready_for_one_share_paper_trial":
        return "ready_for_guarded_validate"
    return "unknown"


def _summary(stage: str) -> str:
    summaries = {
        "blocked_before_paper_window": "The workflow is safely blocked before any IBKR quote capture, validation, or paper order.",
        "ready_for_guarded_validate": "The environment is ready; the next safe step is guarded validate-only execution.",
        "validate_required": "The pipeline produced validation payloads; validate-only API results are required before paper.",
        "ready_for_explicit_paper_submit": "A one-share paper payload appears ready for explicit manual submission.",
        "paper_submitted_needs_reconciliation": "A paper order was submitted and must be reconciled against TWS, audit, and P&L readbacks.",
        "paper_reconciled": "The paper order has matching gate, audit, TWS readback, and P&L evidence.",
    }
    return summaries.get(stage, "The paper trial workflow stage could not be classified from current reports.")


def _next_actions(
    stage: str,
    audit: Optional[Mapping[str, Any]],
    runbook: Optional[Mapping[str, Any]],
) -> list[str]:
    if stage == "blocked_before_paper_window":
        actions = []
        if isinstance(audit, Mapping):
            next_steps = audit.get("next_steps", [])
            if isinstance(next_steps, list):
                actions.extend(str(step) for step in next_steps)
        if not actions and isinstance(runbook, Mapping):
            steps = runbook.get("operator_steps", [])
            if isinstance(steps, list):
                actions.extend(str(step) for step in steps)
        return actions or ["Open the latest paper_session_runbook.md and fix the blockers."]
    if stage == "ready_for_guarded_validate":
        return ["Run scripts/run_guarded_paper_trial_session.py with --submit-validate.", "Review validation and readiness reports."]
    if stage == "validate_required":
        return ["Run validate-only checks if missing.", "Review paper_validation_plan.json and paper_readiness_report.json."]
    if stage == "ready_for_explicit_paper_submit":
        return ["Manually review paper_execution_gate.json.", "Submit only with PAPER_ONLY_1_SHARE and a trade session token file."]
    if stage == "paper_submitted_needs_reconciliation":
        return ["Capture TWS orders.", "Capture a P&L snapshot.", "Run build_paper_trial_reconciliation.py."]
    if stage == "paper_reconciled":
        return ["Review fills and stop further trading until the paper session is deliberately reopened."]
    return ["Regenerate audit, guarded session, runbook, status page, and reconciliation reports."]


def _artifacts(paths: Mapping[str, Path]) -> list[EvidenceArtifact]:
    return [
        EvidenceArtifact(
            name=name,
            path=str(path),
            exists=path.exists(),
            status=_artifact_status(path),
            created_at=_artifact_created_at(path),
        )
        for name, path in paths.items()
    ]


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.suffix.lower() == ".html":
        return "present"
    payload = _load_optional_json(path)
    if isinstance(payload, Mapping):
        return str(payload.get("status", "present"))
    return "present"


def _artifact_created_at(path: Path) -> str:
    payload = _load_optional_json(path)
    if isinstance(payload, Mapping):
        value = payload.get("created_at")
        if isinstance(value, str):
            return value
    return ""


def _status(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "missing"
    return str(payload.get("status", "present"))


def _load_optional_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0 or path.suffix.lower() == ".html":
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
