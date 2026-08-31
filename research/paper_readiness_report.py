import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    status: str
    reason: str


@dataclass(frozen=True)
class PaperReadinessReport:
    source: str
    created_at: str
    plan_path: str
    status: str
    candidate_count: int
    validate_payload_count: int
    validate_approved_count: int
    watch_count: int
    reject_count: int
    required_operator_steps: List[str]
    readiness_items: List[ReadinessItem] = field(default_factory=list)


def load_plan(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("paper validation plan must be a JSON object")
    return payload


def build_readiness_report(plan: Mapping[str, Any], *, plan_path: Path) -> PaperReadinessReport:
    candidates = plan.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("paper validation plan candidates must be a list")

    validate_payload_count = 0
    validate_approved_count = 0
    watch_count = 0
    reject_count = 0
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        action = str(candidate.get("action", ""))
        if action == "WATCH":
            watch_count += 1
        if action == "REJECT":
            reject_count += 1
        if candidate.get("validation_payload") is not None:
            validate_payload_count += 1
        result = candidate.get("validation_result")
        if isinstance(result, Mapping) and result.get("approved") is True:
            validate_approved_count += 1

    readiness_items = _readiness_items(
        candidate_count=len(candidates),
        validate_payload_count=validate_payload_count,
        validate_approved_count=validate_approved_count,
    )
    status = "not_ready_for_paper"
    if validate_payload_count > 0 and validate_approved_count == validate_payload_count:
        status = "ready_for_manual_paper_review"
    elif validate_payload_count > 0:
        status = "validate_required"

    return PaperReadinessReport(
        source="paper_readiness_report",
        created_at=datetime.now(timezone.utc).isoformat(),
        plan_path=str(plan_path),
        status=status,
        candidate_count=len(candidates),
        validate_payload_count=validate_payload_count,
        validate_approved_count=validate_approved_count,
        watch_count=watch_count,
        reject_count=reject_count,
        required_operator_steps=_operator_steps(status),
        readiness_items=readiness_items,
    )


def write_readiness_report(report: PaperReadinessReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a manual paper-trading readiness report from a validate-only plan. This script never places orders."
    )
    parser.add_argument("paper_validation_plan", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_readiness_report.json")
    args = parser.parse_args()

    report = build_readiness_report(load_plan(args.paper_validation_plan), plan_path=args.paper_validation_plan)
    write_readiness_report(report, args.output)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _readiness_items(
    *,
    candidate_count: int,
    validate_payload_count: int,
    validate_approved_count: int,
) -> List[ReadinessItem]:
    items = [
        ReadinessItem(
            "diagnostics_candidates",
            "pass" if candidate_count > 0 else "fail",
            "plan contains candidate rows" if candidate_count > 0 else "plan has no candidates",
        ),
        ReadinessItem(
            "validate_payloads",
            "pass" if validate_payload_count > 0 else "fail",
            "at least one validate payload exists" if validate_payload_count > 0 else "no candidate reached validate payload criteria",
        ),
        ReadinessItem(
            "validate_results",
            "pass" if validate_payload_count > 0 and validate_approved_count == validate_payload_count else "warn",
            "all validate payloads are approved"
            if validate_payload_count > 0 and validate_approved_count == validate_payload_count
            else "run with --submit-validate and inspect Trading API approval before paper",
        ),
        ReadinessItem(
            "paper_execution",
            "manual_only",
            "paper orders require TRADE_LOCK, TWS paper readiness, session token, and operator approval",
        ),
        ReadinessItem(
            "live_execution",
            "blocked",
            "live trading remains disabled and is outside this readiness report",
        ),
    ]
    return items


def _operator_steps(status: str) -> List[str]:
    steps = [
        "Confirm TWS or IB Gateway is logged into the paper account.",
        "Confirm market data type and quote freshness in the recorder report.",
        "Review diagnostics and paper validation plan manually.",
        "Run validate-only API checks before any paper order.",
        "Use TRADE_LOCK only for an explicit paper-trading window.",
        "Keep live trading disabled.",
    ]
    if status == "ready_for_manual_paper_review":
        steps.append("If proceeding, submit at most one 1-share paper order through the existing Trading API gates.")
    return steps


if __name__ == "__main__":
    raise SystemExit(main())
