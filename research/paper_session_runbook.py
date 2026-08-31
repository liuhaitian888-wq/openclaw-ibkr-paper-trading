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
class RunbookCommand:
    name: str
    purpose: str
    command: str


@dataclass(frozen=True)
class PaperSessionRunbook:
    source: str
    created_at: str
    status: str
    summary: str
    environment_status: str
    guarded_session_status: str
    blockers: list[str] = field(default_factory=list)
    operator_steps: list[str] = field(default_factory=list)
    commands: list[RunbookCommand] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


def build_runbook(
    audit: Mapping[str, Any],
    guarded_session: Optional[Mapping[str, Any]] = None,
    *,
    symbols: str = "AAPL,MSFT,SPY",
    samples: int = 30,
    interval_seconds: float = 60.0,
    market_data_type: int = 3,
) -> PaperSessionRunbook:
    environment_status = str(audit.get("status", "unknown"))
    guarded_status = "missing" if guarded_session is None else str(guarded_session.get("status", "unknown"))
    blockers = _blockers(audit, guarded_session)
    status = _runbook_status(environment_status, guarded_status, blockers)
    commands = _commands(
        symbols=symbols,
        samples=samples,
        interval_seconds=interval_seconds,
        market_data_type=market_data_type,
        environment_status=environment_status,
    )
    return PaperSessionRunbook(
        source="paper_session_runbook",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        summary=_summary(status, environment_status, guarded_status),
        environment_status=environment_status,
        guarded_session_status=guarded_status,
        blockers=blockers,
        operator_steps=_operator_steps(status, blockers),
        commands=commands,
        artifacts=_artifacts(audit, guarded_session),
    )


def write_runbook_json(runbook: PaperSessionRunbook, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(runbook), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_runbook_markdown(runbook: PaperSessionRunbook, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(runbook), encoding="utf-8")
    return output


def render_markdown(runbook: PaperSessionRunbook) -> str:
    lines = [
        "# Paper Trial Session Runbook",
        "",
        f"Generated: `{runbook.created_at}`",
        "",
        f"Status: `{runbook.status}`",
        "",
        runbook.summary,
        "",
        "## Current State",
        "",
        f"- Environment audit: `{runbook.environment_status}`",
        f"- Guarded session: `{runbook.guarded_session_status}`",
        "",
        "## Blockers",
        "",
    ]
    if runbook.blockers:
        lines.extend(f"- {blocker}" for blocker in runbook.blockers)
    else:
        lines.append("- None detected by the latest reports.")
    lines.extend(["", "## Operator Steps", ""])
    lines.extend(f"{index}. {step}" for index, step in enumerate(runbook.operator_steps, start=1))
    lines.extend(["", "## Commands", ""])
    for command in runbook.commands:
        lines.extend(
            [
                f"### {command.name}",
                "",
                command.purpose,
                "",
                "```bash",
                command.command,
                "```",
                "",
            ]
        )
    lines.extend(["## Artifacts", ""])
    for name, path in sorted(runbook.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a human-readable runbook from paper environment and guarded-session reports."
    )
    parser.add_argument("--audit-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_environment_audit.json")
    parser.add_argument("--guarded-session-report", type=Path, default=PROJECT_ROOT / "reports" / "guarded_paper_trial_session.json")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_runbook.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_runbook.md")
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--market-data-type", type=int, default=3)
    args = parser.parse_args()

    audit = _load_json_object(args.audit_report)
    guarded = _load_optional_json_object(args.guarded_session_report)
    runbook = build_runbook(
        audit,
        guarded,
        symbols=args.symbols,
        samples=args.samples,
        interval_seconds=args.interval_seconds,
        market_data_type=args.market_data_type,
    )
    write_runbook_json(runbook, args.output_json)
    write_runbook_markdown(runbook, args.output_md)
    print(json.dumps(asdict(runbook), indent=2, sort_keys=True))
    return 0


def _blockers(audit: Mapping[str, Any], guarded_session: Optional[Mapping[str, Any]]) -> list[str]:
    blockers = []
    items = audit.get("items", [])
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if item.get("required") is not True:
                continue
            if item.get("status") not in {"fail", "unknown"}:
                continue
            blockers.append(f"{item.get('name')}: {item.get('detail')}")
    if guarded_session is not None and guarded_session.get("status") == "environment_blocked":
        blockers.append(str(guarded_session.get("reason", "guarded session was blocked")))
    return _dedupe(blockers)


def _runbook_status(environment_status: str, guarded_status: str, blockers: list[str]) -> str:
    if environment_status != "ready_for_one_share_paper_trial":
        return "environment_blocked"
    if guarded_status == "paper_submitted":
        return "paper_submitted_review_required"
    if guarded_status in {"ready_for_explicit_paper_submit", "validate_required"}:
        return guarded_status
    if blockers:
        return "attention_required"
    return "ready_to_run_guarded_validate"


def _summary(status: str, environment_status: str, guarded_status: str) -> str:
    if status == "environment_blocked":
        return "The machine is not ready for a paper trial. Fix the blockers before collecting IBKR quotes or validating orders."
    if status == "ready_to_run_guarded_validate":
        return "The environment is ready. Run the guarded session with validate-only first."
    if status == "validate_required":
        return "The environment is ready and the pipeline found validate payloads. Run validate-only checks before any paper order."
    if status == "ready_for_explicit_paper_submit":
        return "A validated one-share paper payload is ready for manual review and explicit submission."
    if status == "paper_submitted_review_required":
        return "A paper order was submitted. Review audit records, TWS state, and fills before any further action."
    return f"Environment status is {environment_status}; guarded session status is {guarded_status}."


def _operator_steps(status: str, blockers: list[str]) -> list[str]:
    if status == "environment_blocked":
        steps = [
            "Open TWS or IB Gateway and log into the paper account.",
            "Enable TWS API access on localhost and confirm paper port 7497.",
            "Start the Trading API through TRADE_LOCK when you intentionally want a paper window.",
            "Regenerate the environment audit.",
            "Run the guarded paper-trial session after the audit is ready.",
        ]
        if any("trade_session_token" in blocker for blocker in blockers):
            steps.insert(3, "Generate or provide a fresh trade session token.")
        return steps
    if status == "ready_to_run_guarded_validate":
        return [
            "Run the guarded session with --submit-validate.",
            "Review the validation plan, readiness report, and execution gate report.",
            "Do not use --execute-paper until the execution gate is ready and manually reviewed.",
        ]
    if status == "validate_required":
        return [
            "Run the guarded session again with --submit-validate if validation results are missing.",
            "Inspect reports/paper_validation_plan.json for approved=true validation results.",
            "Proceed only to a one-share paper order after the readiness and execution gate reports agree.",
        ]
    if status == "ready_for_explicit_paper_submit":
        return [
            "Review the selected payload in reports/paper_execution_gate.json.",
            "Confirm order side, quantity, limit price, account, and TWS paper state manually.",
            "Submit only with --execute-paper --confirm PAPER_ONLY_1_SHARE and a trade session token file.",
        ]
    if status == "paper_submitted_review_required":
        return [
            "Inspect TWS open orders, fills, and account positions.",
            "Fetch /v1/orders/audit for the submitted idempotency key.",
            "Do not submit another order until reconciliation is clean.",
        ]
    return ["Inspect the reports and rerun the guarded session."]


def _commands(
    *,
    symbols: str,
    samples: int,
    interval_seconds: float,
    market_data_type: int,
    environment_status: str,
) -> list[RunbookCommand]:
    audit_cmd = ".venv313/bin/python scripts/audit_paper_trading_readiness.py"
    guarded_base = (
        ".venv313/bin/python scripts/run_guarded_paper_trial_session.py "
        f"--symbols {symbols} --samples {samples} --interval-seconds {interval_seconds:g} "
        f"--market-data-type {market_data_type}"
    )
    commands = [
        RunbookCommand(
            "Open Mode Control",
            "Use the interactive gateway menu to enter STOP, DEV_LOCK, or TRADE_LOCK.",
            "scripts/control_trading_mode.command",
        ),
        RunbookCommand(
            "Start Trade Lock API",
            "Start the API directly in TRADE_LOCK after opening TWS paper and preparing a session token.",
            "scripts/start_trade_lock_api.command",
        ),
        RunbookCommand(
            "Check Gateway Health",
            "Print the current Trading API /health response.",
            "scripts/check_gateway_health.command",
        ),
        RunbookCommand(
            "Audit Environment",
            "Regenerate the local paper-trading readiness report.",
            audit_cmd,
        ),
        RunbookCommand(
            "Guarded Dry Run",
            "Run the guarded session. It stops before market data if the environment is not ready.",
            guarded_base,
        ),
        RunbookCommand(
            "Simulated Ready Rehearsal",
            "Exercise the ready-environment code path without IBKR data, API validation, or orders.",
            ".venv313/bin/python scripts/rehearse_paper_trial_workflow.py",
        ),
        RunbookCommand(
            "Build Preflight Checklist",
            "Generate the machine-check and manual-confirmation checklist for the real IBKR paper window.",
            ".venv313/bin/python scripts/build_paper_trial_preflight_checklist.py",
        ),
        RunbookCommand(
            "Monitor Readiness",
            "Poll Trading API and TWS readiness without starting quote capture, validation, or orders.",
            ".venv313/bin/python scripts/monitor_paper_trial_readiness.py --max-attempts 60 --interval-seconds 5",
        ),
        RunbookCommand(
            "Build Runbook",
            "Regenerate this operator runbook from the latest reports.",
            ".venv313/bin/python scripts/build_paper_session_runbook.py",
        ),
        RunbookCommand(
            "Capture TWS Orders",
            "After any paper order, capture open orders, completed orders, and executions.",
            ".venv313/bin/python scripts/list_tws_orders.py > reports/tws_orders_snapshot.json",
        ),
        RunbookCommand(
            "Capture P&L Snapshot",
            "After any paper order, capture a read-only paper account P&L sample.",
            ".venv313/bin/python scripts/record_account_pnl.py --samples 1 --interval-seconds 1",
        ),
        RunbookCommand(
            "Reconcile Paper Trial",
            "Cross-check execution gate, SQLite audit, TWS readback, and P&L snapshot.",
            ".venv313/bin/python scripts/build_paper_trial_reconciliation.py",
        ),
        RunbookCommand(
            "Build Evidence Bundle",
            "Summarize the latest workflow stage and artifacts into one evidence report.",
            ".venv313/bin/python scripts/build_paper_trial_evidence_bundle.py",
        ),
    ]
    if environment_status == "ready_for_one_share_paper_trial":
        commands.extend(
            [
                RunbookCommand(
                    "Guarded Validate",
                    "Run read-only IBKR quote capture, diagnostics, and validate-only API checks.",
                    guarded_base + " --submit-validate",
                ),
                RunbookCommand(
                    "Explicit One-Share Paper",
                    "Submit at most one one-share paper limit order after manual review.",
                    guarded_base
                    + " --submit-validate --execute-paper --confirm PAPER_ONLY_1_SHARE "
                    + "--trade-session-token-file ~/Documents/openclaw_shared/trade_session_token",
                ),
                RunbookCommand(
                    "Reviewed One-Share Paper",
                    "Submit the reviewed one-share paper payload only after pre-submit review and explicit confirmation.",
                    ".venv313/bin/python scripts/build_paper_execution_gate.py "
                    + "reports/paper_readiness_report.json reports/paper_validation_plan.json "
                    + "--execute-paper --confirm PAPER_ONLY_1_SHARE "
                    + "--trade-session-token-file ~/Documents/openclaw_shared/trade_session_token "
                    + "--pre-submit-review reports/paper_pre_submit_review.json "
                    + "--api-url http://192.168.64.1:8787",
                ),
            ]
        )
    return commands


def _artifacts(audit: Mapping[str, Any], guarded_session: Optional[Mapping[str, Any]]) -> dict[str, str]:
    artifacts = {
        "paper_environment_audit": "reports/paper_environment_audit.json",
        "paper_trial_reconciliation": "reports/paper_trial_reconciliation.json",
        "paper_trial_evidence_bundle": "reports/paper_trial_evidence_bundle.json",
        "paper_trial_preflight_checklist": "reports/paper_trial_preflight_checklist.json",
        "paper_trial_readiness_monitor": "reports/paper_trial_readiness_monitor.json",
        "paper_trial_rehearsal": "reports/paper_trial_rehearsal/paper_trial_rehearsal.json",
        "paper_session_status": "reports/paper_session_status.html",
        "tws_orders_snapshot": "reports/tws_orders_snapshot.json",
        "pnl_timeseries": "reports/pnl_timeseries.jsonl",
    }
    guarded_artifacts = guarded_session.get("artifacts", {}) if isinstance(guarded_session, Mapping) else {}
    if isinstance(guarded_artifacts, Mapping):
        artifacts.update({str(key): str(value) for key, value in guarded_artifacts.items()})
    audit_health = audit.get("api_url")
    if audit_health:
        artifacts["api_url"] = str(audit_health)
    return artifacts


def _load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_optional_json_object(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    return _load_json_object(path)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
