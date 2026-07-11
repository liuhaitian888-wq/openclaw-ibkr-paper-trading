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
class PreflightCheck:
    name: str
    status: str
    detail: str
    evidence: str


@dataclass(frozen=True)
class PaperTrialPreflightChecklist:
    source: str
    created_at: str
    status: str
    next_allowed_action: str
    machine_checks: list[PreflightCheck] = field(default_factory=list)
    manual_confirmations: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


def build_preflight_checklist(
    audit: Mapping[str, Any],
    runbook: Mapping[str, Any],
    *,
    rehearsal: Optional[Mapping[str, Any]] = None,
) -> PaperTrialPreflightChecklist:
    machine_checks = _machine_checks(audit, runbook, rehearsal)
    status = _status(machine_checks)
    return PaperTrialPreflightChecklist(
        source="paper_trial_preflight_checklist",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        next_allowed_action=_next_allowed_action(status),
        machine_checks=machine_checks,
        manual_confirmations=_manual_confirmations(status),
        stop_conditions=_stop_conditions(),
        commands=_commands(status),
        artifacts={
            "environment_audit": "reports/paper_environment_audit.json",
            "runbook": "reports/paper_session_runbook.json",
            "rehearsal": "reports/paper_trial_rehearsal/paper_trial_rehearsal.json",
            "output_json": "reports/paper_trial_preflight_checklist.json",
            "output_md": "reports/paper_trial_preflight_checklist.md",
        },
    )


def write_preflight_json(checklist: PaperTrialPreflightChecklist, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(checklist), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_preflight_markdown(checklist: PaperTrialPreflightChecklist, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(checklist), encoding="utf-8")
    return output


def render_markdown(checklist: PaperTrialPreflightChecklist) -> str:
    lines = [
        "# Paper Trial Preflight Checklist",
        "",
        f"Generated: `{checklist.created_at}`",
        "",
        f"Status: `{checklist.status}`",
        "",
        f"Next allowed action: `{checklist.next_allowed_action}`",
        "",
        "## Machine Checks",
        "",
    ]
    for check in checklist.machine_checks:
        lines.extend(
            [
                f"### {check.name}",
                "",
                f"- Status: `{check.status}`",
                f"- Detail: {check.detail}",
                f"- Evidence: `{check.evidence}`",
                "",
            ]
        )
    lines.extend(["## Manual Confirmations", ""])
    lines.extend(f"{index}. {step}" for index, step in enumerate(checklist.manual_confirmations, start=1))
    lines.extend(["", "## Stop Conditions", ""])
    lines.extend(f"- {condition}" for condition in checklist.stop_conditions)
    lines.extend(["", "## Commands", ""])
    for command in checklist.commands:
        lines.extend(["```bash", command, "```", ""])
    lines.extend(["## Artifacts", ""])
    for name, path in sorted(checklist.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a one-share IBKR paper-trial preflight checklist from current local evidence."
    )
    parser.add_argument("--audit-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_environment_audit.json")
    parser.add_argument("--runbook-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_runbook.json")
    parser.add_argument(
        "--rehearsal-report",
        type=Path,
        default=PROJECT_ROOT / "reports" / "paper_trial_rehearsal" / "paper_trial_rehearsal.json",
    )
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.md")
    args = parser.parse_args()

    checklist = build_preflight_checklist(
        _load_json_object(args.audit_report),
        _load_json_object(args.runbook_json),
        rehearsal=_load_optional_json_object(args.rehearsal_report),
    )
    write_preflight_json(checklist, args.output_json)
    write_preflight_markdown(checklist, args.output_md)
    print(json.dumps(asdict(checklist), indent=2, sort_keys=True))
    return 0


def _machine_checks(
    audit: Mapping[str, Any],
    runbook: Mapping[str, Any],
    rehearsal: Optional[Mapping[str, Any]],
) -> list[PreflightCheck]:
    audit_status = str(audit.get("status", "missing"))
    runbook_status = str(runbook.get("status", "missing"))
    return [
        PreflightCheck(
            "environment_audit_ready",
            "pass" if audit_status == "ready_for_one_share_paper_trial" else "fail",
            f"environment audit status is {audit_status}",
            "reports/paper_environment_audit.json",
        ),
        PreflightCheck(
            "runbook_ready",
            "pass" if runbook_status in {"ready_to_run_guarded_validate", "validate_required", "ready_for_explicit_paper_submit"} else "fail",
            f"runbook status is {runbook_status}",
            "reports/paper_session_runbook.json",
        ),
        PreflightCheck(
            "safe_rehearsal_completed",
            "pass" if _rehearsal_is_clean(rehearsal) else "fail",
            _rehearsal_detail(rehearsal),
            "reports/paper_trial_rehearsal/paper_trial_rehearsal.json",
        ),
        PreflightCheck(
            "no_existing_paper_submission",
            "pass" if runbook_status != "paper_submitted_review_required" else "fail",
            "latest runbook does not report an unreconciled paper submission"
            if runbook_status != "paper_submitted_review_required"
            else "latest runbook reports a paper submission that requires review",
            "reports/paper_session_runbook.json",
        ),
    ]


def _status(checks: list[PreflightCheck]) -> str:
    failed = [check.name for check in checks if check.status != "pass"]
    if "environment_audit_ready" in failed or "runbook_ready" in failed:
        return "blocked_before_real_ibkr_window"
    if failed:
        return "attention_required_before_real_ibkr_window"
    return "ready_for_validate_only_window"


def _next_allowed_action(status: str) -> str:
    if status == "ready_for_validate_only_window":
        return "run_guarded_validate_only"
    if status == "attention_required_before_real_ibkr_window":
        return "review_failed_preflight_checks"
    return "fix_environment_and_refresh_reports"


def _manual_confirmations(status: str) -> list[str]:
    common = [
        "TWS or IB Gateway is visibly logged into the paper account, not a live account.",
        "The visible account identifier starts with DU and matches the /health paper_account.",
        "The intended order size remains exactly one share with a small limit-order value.",
        "No open order or position in TWS would make the test ambiguous.",
    ]
    if status == "ready_for_validate_only_window":
        return common + [
            "Run validate-only first and inspect every generated report before considering a paper submit.",
            "Keep --execute-paper absent until the execution gate explicitly reaches manual review readiness.",
        ]
    return common + ["Do not collect IBKR quotes or validate orders until the failed checks are fixed."]


def _stop_conditions() -> list[str]:
    return [
        "Any report shows a live account, a non-DU account, or multiple managed accounts.",
        "TRADING_MODE is not PAPER during a real IBKR paper window.",
        "TRADING_KILL_SWITCH is true when paper submission is intended, or false outside an intentional window.",
        "ALLOW_PAPER_TRANSMIT is true without a fresh trade session token.",
        "TWS/API health changes between validate-only and paper submission.",
        "The generated payload is not a one-share limit order.",
    ]


def _commands(status: str) -> list[str]:
    commands = [
        ".venv313/bin/python scripts/refresh_paper_trial_reports.py --samples 1 --interval-seconds 0",
        ".venv313/bin/python scripts/build_paper_trial_preflight_checklist.py",
    ]
    if status == "ready_for_validate_only_window":
        commands.append(
            ".venv313/bin/python scripts/run_guarded_paper_trial_session.py "
            "--symbols AAPL,MSFT,SPY --samples 30 --interval-seconds 60 --market-data-type 3 --submit-validate"
        )
    return commands


def _rehearsal_is_clean(rehearsal: Optional[Mapping[str, Any]]) -> bool:
    if rehearsal is None:
        return False
    return (
        rehearsal.get("status") == "completed"
        and rehearsal.get("ibkr_market_data_used") is False
        and rehearsal.get("trading_api_validate_used") is False
        and rehearsal.get("paper_order_used") is False
    )


def _rehearsal_detail(rehearsal: Optional[Mapping[str, Any]]) -> str:
    if rehearsal is None:
        return "simulated rehearsal report is missing"
    return (
        f"status={rehearsal.get('status')}; "
        f"ibkr_market_data_used={rehearsal.get('ibkr_market_data_used')}; "
        f"trading_api_validate_used={rehearsal.get('trading_api_validate_used')}; "
        f"paper_order_used={rehearsal.get('paper_order_used')}"
    )


def _load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_optional_json_object(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    return _load_json_object(path)


if __name__ == "__main__":
    raise SystemExit(main())
