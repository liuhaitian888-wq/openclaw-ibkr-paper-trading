import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings


@dataclass(frozen=True)
class PaperValidationCandidate:
    symbol: str
    action: str
    reason: str
    verdict: str
    score: float
    latest_z_score: Optional[float]
    last_price: float
    validation_payload: Optional[dict[str, Any]] = None
    validation_result: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class PaperValidationPlan:
    source: str
    created_at: str
    diagnostics_path: str
    mode: str
    entry_z: float
    quantity: int
    candidate_count: int
    validate_payload_count: int
    candidates: List[PaperValidationCandidate] = field(default_factory=list)


def build_plan(
    diagnostics: Sequence[Mapping[str, Any]],
    *,
    diagnostics_path: Path,
    entry_z: float = 1.0,
    quantity: int = 1,
    allowed_verdicts: Iterable[str] = ("watchlist", "research_candidate"),
) -> PaperValidationPlan:
    allowed = {item.strip() for item in allowed_verdicts if item.strip()}
    candidates = [
        _candidate_from_item(item, entry_z=entry_z, quantity=quantity, allowed_verdicts=allowed)
        for item in diagnostics
    ]
    validate_count = sum(1 for candidate in candidates if candidate.validation_payload is not None)
    return PaperValidationPlan(
        source="paper_validation_plan",
        created_at=datetime.now(timezone.utc).isoformat(),
        diagnostics_path=str(diagnostics_path),
        mode="validate_only",
        entry_z=entry_z,
        quantity=quantity,
        candidate_count=len(candidates),
        validate_payload_count=validate_count,
        candidates=candidates,
    )


def load_diagnostics(path: Path) -> List[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("diagnostics JSON must be a list")
    return payload


def write_plan(plan: PaperValidationPlan, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(plan), indent=2, sort_keys=True), encoding="utf-8")
    return output


def submit_validate_payloads(plan: PaperValidationPlan, *, api_url: str, api_key: str, timeout: float) -> PaperValidationPlan:
    candidates = []
    for candidate in plan.candidates:
        if candidate.validation_payload is None:
            candidates.append(candidate)
            continue
        result = _request_json(
            "POST",
            "/v1/orders/validate/limit",
            candidate.validation_payload,
            api_url=api_url,
            api_key=api_key,
            timeout=timeout,
        )
        candidates.append(
            PaperValidationCandidate(
                symbol=candidate.symbol,
                action=candidate.action,
                reason=candidate.reason,
                verdict=candidate.verdict,
                score=candidate.score,
                latest_z_score=candidate.latest_z_score,
                last_price=candidate.last_price,
                validation_payload=candidate.validation_payload,
                validation_result=result,
            )
        )
    return PaperValidationPlan(
        source=plan.source,
        created_at=plan.created_at,
        diagnostics_path=plan.diagnostics_path,
        mode=plan.mode,
        entry_z=plan.entry_z,
        quantity=plan.quantity,
        candidate_count=plan.candidate_count,
        validate_payload_count=plan.validate_payload_count,
        candidates=candidates,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert diagnostics into a validate-only paper trading plan. This script never stages or places orders."
    )
    parser.add_argument("diagnostics_json", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_validation_plan.json")
    parser.add_argument("--entry-z", type=float, default=1.0)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--submit-validate", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=15.0)
    args = parser.parse_args()

    plan = build_plan(
        load_diagnostics(args.diagnostics_json),
        diagnostics_path=args.diagnostics_json,
        entry_z=args.entry_z,
        quantity=args.quantity,
    )
    if args.submit_validate:
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        plan = submit_validate_payloads(
            plan,
            api_url=args.api_url,
            api_key=api_key,
            timeout=args.api_timeout,
        )
    write_plan(plan, args.output)
    print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    return 0


def _candidate_from_item(
    item: Mapping[str, Any],
    *,
    entry_z: float,
    quantity: int,
    allowed_verdicts: set[str],
) -> PaperValidationCandidate:
    symbol = str(item.get("symbol", "")).upper()
    diagnostics = item.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}
    verdict = str(diagnostics.get("verdict", "unknown"))
    score = float(diagnostics.get("mean_reversion_score", 0.0) or 0.0)
    latest_z = _optional_float(diagnostics.get("latest_z_score"))
    last_price = float(item.get("last_price", 0.0) or 0.0)

    action = "REJECT"
    reason = "diagnostics verdict is not eligible for paper validation"
    payload = None
    if verdict in allowed_verdicts:
        if latest_z is None:
            action = "WATCH"
            reason = "eligible verdict but latest z-score is unavailable"
        elif latest_z <= -abs(entry_z):
            action = "VALIDATE_BUY_LIMIT"
            reason = "eligible mean-reversion candidate with negative z-score entry"
            payload = _validation_payload(symbol, "BUY", quantity, last_price)
        elif latest_z >= abs(entry_z):
            action = "WATCH"
            reason = "positive z-score observed; long-only module should wait for a pullback"
        else:
            action = "WATCH"
            reason = "eligible verdict but z-score is inside the no-trade band"

    return PaperValidationCandidate(
        symbol=symbol,
        action=action,
        reason=reason,
        verdict=verdict,
        score=score,
        latest_z_score=latest_z,
        last_price=last_price,
        validation_payload=payload,
    )


def _validation_payload(symbol: str, side: str, quantity: int, limit_price: float) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "limit_price": round(float(limit_price), 2),
        "idempotency_key": (
            f"validate-{symbol.lower()}-{side.lower()}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        )[:64],
        "source": "paper_validation_plan",
    }


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _request_json(
    method: str,
    path: str,
    payload: Mapping[str, Any],
    *,
    api_url: str,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
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
    result["validate_round_trip_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
