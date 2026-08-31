import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CONFIRM_PHRASE = "PAPER_ONLY_1_SHARE"


@dataclass(frozen=True)
class PaperExecutionGateReport:
    source: str
    created_at: str
    mode: str
    status: str
    reason: str
    readiness_path: str
    plan_path: str
    selected_symbol: Optional[str] = None
    selected_payload: Optional[dict[str, Any]] = None
    health: Optional[dict[str, Any]] = None
    submission_result: Optional[dict[str, Any]] = None


RequestJson = Callable[[str, str, Optional[Mapping[str, Any]], str, str, float], dict[str, Any]]


def load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def build_gate_report(
    readiness: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    readiness_path: Path,
    plan_path: Path,
) -> PaperExecutionGateReport:
    selected = _selected_candidate(readiness, plan)
    if selected is None:
        return PaperExecutionGateReport(
            source="paper_execution_gate",
            created_at=datetime.now(timezone.utc).isoformat(),
            mode="dry_run",
            status="blocked",
            reason="no approved validate payload is ready for manual paper review",
            readiness_path=str(readiness_path),
            plan_path=str(plan_path),
        )
    payload = dict(selected["validation_payload"])
    return PaperExecutionGateReport(
        source="paper_execution_gate",
        created_at=datetime.now(timezone.utc).isoformat(),
        mode="dry_run",
        status="ready_for_explicit_paper_submit",
        reason="readiness report and validation result allow one explicit paper limit submission",
        readiness_path=str(readiness_path),
        plan_path=str(plan_path),
        selected_symbol=str(selected.get("symbol", payload.get("symbol", ""))).upper(),
        selected_payload=payload,
    )


def execute_if_confirmed(
    report: PaperExecutionGateReport,
    *,
    confirm: str,
    trade_session_token: str,
    api_url: str,
    api_key: str,
    timeout: float,
    pre_submit_review: Optional[Mapping[str, Any]] = None,
    max_review_age_seconds: float = 300.0,
    request_json: RequestJson = None,
) -> PaperExecutionGateReport:
    if report.status != "ready_for_explicit_paper_submit" or report.selected_payload is None:
        return _replace_report(report, mode="execute_paper", status="blocked", reason="gate report is not ready")
    if confirm != CONFIRM_PHRASE:
        return _replace_report(report, mode="execute_paper", status="blocked", reason=f"confirmation phrase must be {CONFIRM_PHRASE}")
    if not trade_session_token:
        return _replace_report(report, mode="execute_paper", status="blocked", reason="trade session token is required")
    review_block = _pre_submit_review_block_reason(
        pre_submit_review,
        selected_payload=report.selected_payload,
        max_age_seconds=max_review_age_seconds,
    )
    if review_block:
        return _replace_report(report, mode="execute_paper", status="blocked", reason=review_block)
    requester = request_json or _request_json
    health = requester("GET", "/health", None, api_url, api_key, timeout)
    health_block = _health_block_reason(health)
    if health_block:
        return _replace_report(report, mode="execute_paper", status="blocked", reason=health_block, health=health)

    payload = dict(report.selected_payload)
    payload["trade_session_token"] = trade_session_token
    result = requester("POST", "/v1/orders/paper/limit", payload, api_url, api_key, timeout)
    return _replace_report(
        report,
        mode="execute_paper",
        status="submitted" if result.get("approved") is True else "rejected",
        reason="paper limit endpoint returned approved=true" if result.get("approved") is True else "paper limit endpoint did not approve submission",
        health=health,
        submission_result=result,
    )


def write_report(report: PaperExecutionGateReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate at most one explicit 1-share paper limit order from a readiness report. Dry-run by default."
    )
    parser.add_argument("paper_readiness_report", type=Path)
    parser.add_argument("paper_validation_plan", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--execute-paper", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--trade-session-token-file", type=Path)
    parser.add_argument("--pre-submit-review", type=Path)
    parser.add_argument("--max-review-age-seconds", type=float, default=300.0)
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=20.0)
    args = parser.parse_args()

    report = build_gate_report(
        load_json_object(args.paper_readiness_report),
        load_json_object(args.paper_validation_plan),
        readiness_path=args.paper_readiness_report,
        plan_path=args.paper_validation_plan,
    )
    if args.execute_paper:
        token = ""
        if args.trade_session_token_file is not None and args.trade_session_token_file.exists():
            token = args.trade_session_token_file.read_text(encoding="utf-8").strip()
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        report = execute_if_confirmed(
            report,
            confirm=args.confirm,
            trade_session_token=token,
            api_url=args.api_url,
            api_key=api_key,
            timeout=args.api_timeout,
            pre_submit_review=_load_optional_json(args.pre_submit_review),
            max_review_age_seconds=args.max_review_age_seconds,
        )
    write_report(report, args.output)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _selected_candidate(
    readiness: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> Optional[Mapping[str, Any]]:
    if readiness.get("status") != "ready_for_manual_paper_review":
        return None
    candidates = plan.get("candidates", [])
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        payload = candidate.get("validation_payload")
        result = candidate.get("validation_result")
        if not isinstance(payload, Mapping) or not isinstance(result, Mapping):
            continue
        if result.get("approved") is not True:
            continue
        if payload.get("side") != "BUY" or payload.get("quantity") != 1:
            continue
        return candidate
    return None


def _health_block_reason(health: Mapping[str, Any]) -> str:
    if health.get("lock_state") != "TRADE_LOCK":
        return f"TRADE_LOCK required; current lock_state={health.get('lock_state')}"
    if health.get("paper_transmit_enabled") is not True:
        return "paper_transmit_enabled must be true"
    if health.get("kill_switch_enabled") is True:
        return "trading kill switch is enabled"
    tws = health.get("tws", {})
    if not isinstance(tws, Mapping) or tws.get("ready_for_orders") is not True:
        return "TWS is not ready for orders"
    return ""


def _pre_submit_review_block_reason(
    review: Optional[Mapping[str, Any]],
    *,
    selected_payload: Mapping[str, Any],
    max_age_seconds: float,
) -> str:
    if review is None:
        return ""
    if review.get("status") != "ready_for_operator_confirmation":
        return f"pre-submit review is not ready; status={review.get('status')}"
    created_at = str(review.get("created_at", ""))
    if created_at:
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return "pre-submit review created_at is invalid"
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
        if age_seconds > max_age_seconds:
            return f"pre-submit review is stale; age_seconds={age_seconds:.1f} max={max_age_seconds:.1f}"
    review_payload = review.get("selected_payload")
    if not isinstance(review_payload, Mapping):
        return "pre-submit review selected_payload is missing"
    for key in ("symbol", "side", "quantity", "limit_price"):
        if review_payload.get(key) != selected_payload.get(key):
            return f"pre-submit review payload mismatch on {key}"
    return ""


def _load_optional_json(path: Optional[Path]) -> Optional[Mapping[str, Any]]:
    if path is None:
        return None
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _replace_report(
    report: PaperExecutionGateReport,
    *,
    mode: str,
    status: str,
    reason: str,
    health: Optional[dict[str, Any]] = None,
    submission_result: Optional[dict[str, Any]] = None,
) -> PaperExecutionGateReport:
    return PaperExecutionGateReport(
        source=report.source,
        created_at=report.created_at,
        mode=mode,
        status=status,
        reason=reason,
        readiness_path=report.readiness_path,
        plan_path=report.plan_path,
        selected_symbol=report.selected_symbol,
        selected_payload=report.selected_payload,
        health=health if health is not None else report.health,
        submission_result=submission_result if submission_result is not None else report.submission_result,
    )


def _request_json(
    method: str,
    path: str,
    payload: Optional[Mapping[str, Any]],
    api_url: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            result = {"status": "ERROR", "error": body}
        result["http_status"] = exc.code
    result["round_trip_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
