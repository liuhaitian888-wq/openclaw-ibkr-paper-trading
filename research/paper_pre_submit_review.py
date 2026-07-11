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
class PreSubmitReviewItem:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class PaperPreSubmitReview:
    source: str
    created_at: str
    status: str
    summary: str
    selected_symbol: str
    selected_payload: Optional[dict[str, Any]]
    review_items: list[PreSubmitReviewItem] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


def build_pre_submit_review(
    *,
    readiness_monitor: Optional[Mapping[str, Any]],
    execution_gate: Optional[Mapping[str, Any]],
    tws_orders: Optional[Mapping[str, Any]],
    pnl_snapshot: Optional[Mapping[str, Any]],
    artifact_paths: Mapping[str, Path],
) -> PaperPreSubmitReview:
    selected_payload = _mapping_or_none(_value(execution_gate, "selected_payload"))
    selected_symbol = str(_value(execution_gate, "selected_symbol") or "")
    items = [
        _item(
            "readiness_monitor",
            readiness_monitor is not None and readiness_monitor.get("status") == "ready_for_validate_only_window",
            f"status={_status(readiness_monitor)}",
        ),
        _item(
            "execution_gate",
            execution_gate is not None and execution_gate.get("status") == "ready_for_explicit_paper_submit",
            f"status={_status(execution_gate)}; selected_symbol={selected_symbol or 'missing'}",
        ),
        _item(
            "one_share_buy_payload",
            _one_share_buy_payload(selected_payload),
            _payload_detail(selected_payload),
        ),
        _item(
            "tws_has_no_open_orders",
            tws_orders is not None and tws_orders.get("status") == "ok" and int(tws_orders.get("open_order_count", -1)) == 0,
            f"status={_status(tws_orders)}; open_order_count={_value(tws_orders, 'open_order_count')}; execution_count={_value(tws_orders, 'execution_count')}",
        ),
        _item(
            "pnl_baseline_captured",
            pnl_snapshot is not None and bool(pnl_snapshot.get("account")),
            _pnl_detail(pnl_snapshot),
        ),
    ]
    ready = all(item.status == "pass" for item in items)
    return PaperPreSubmitReview(
        source="paper_pre_submit_review",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="ready_for_operator_confirmation" if ready else "blocked",
        summary=(
            "Pre-submit checks passed; explicit PAPER_ONLY_1_SHARE confirmation is still required."
            if ready
            else "Pre-submit checks found blockers; do not submit paper order."
        ),
        selected_symbol=selected_symbol,
        selected_payload=dict(selected_payload) if selected_payload is not None else None,
        review_items=items,
        artifacts={name: str(path) for name, path in artifact_paths.items()},
    )


def write_review_json(review: PaperPreSubmitReview, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(review), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_review_markdown(review: PaperPreSubmitReview, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Paper Pre-Submit Review",
        "",
        f"Generated: `{review.created_at}`",
        "",
        f"Status: `{review.status}`",
        "",
        review.summary,
        "",
        f"Selected symbol: `{review.selected_symbol or 'missing'}`",
        "",
        "## Review Items",
        "",
    ]
    lines.extend(f"- `{item.name}`: `{item.status}`; {item.detail}" for item in review.review_items)
    lines.extend(["", "## Artifacts", ""])
    lines.extend(f"- `{name}`: `{path}`" for name, path in sorted(review.artifacts.items()))
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a no-order review report before explicit one-share paper submission.")
    parser.add_argument("--readiness-monitor", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_readiness_monitor.json")
    parser.add_argument("--execution-gate", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--tws-orders", type=Path, default=PROJECT_ROOT / "reports" / "tws_orders_snapshot_pre_submit_review.json")
    parser.add_argument("--pnl-jsonl", type=Path, default=PROJECT_ROOT / "reports" / "pnl_pre_submit_review.jsonl")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_pre_submit_review.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "paper_pre_submit_review.md")
    args = parser.parse_args()

    artifacts = {
        "readiness_monitor": args.readiness_monitor,
        "execution_gate": args.execution_gate,
        "tws_orders": args.tws_orders,
        "pnl_jsonl": args.pnl_jsonl,
    }
    review = build_pre_submit_review(
        readiness_monitor=_load_optional_json(args.readiness_monitor),
        execution_gate=_load_optional_json(args.execution_gate),
        tws_orders=_load_optional_json(args.tws_orders),
        pnl_snapshot=_load_last_jsonl(args.pnl_jsonl),
        artifact_paths=artifacts,
    )
    write_review_json(review, args.output_json)
    write_review_markdown(review, args.output_md)
    print(json.dumps(asdict(review), indent=2, sort_keys=True))
    return 0 if review.status == "ready_for_operator_confirmation" else 2


def _item(name: str, condition: bool, detail: str) -> PreSubmitReviewItem:
    return PreSubmitReviewItem(name=name, status="pass" if condition else "fail", detail=detail)


def _one_share_buy_payload(payload: Optional[Mapping[str, Any]]) -> bool:
    if payload is None:
        return False
    return payload.get("side") == "BUY" and payload.get("quantity") == 1 and float(payload.get("limit_price", 0.0) or 0.0) > 0


def _payload_detail(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "selected_payload=missing"
    return (
        f"symbol={payload.get('symbol')}; side={payload.get('side')}; "
        f"quantity={payload.get('quantity')}; limit_price={payload.get('limit_price')}"
    )


def _pnl_detail(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "pnl_snapshot=missing"
    return (
        f"account={payload.get('account')}; net_liquidation={payload.get('net_liquidation')}; "
        f"open_positions={payload.get('open_positions')}"
    )


def _status(payload: Optional[Mapping[str, Any]]) -> str:
    if payload is None:
        return "missing"
    return str(payload.get("status", "present"))


def _value(payload: Optional[Mapping[str, Any]], key: str) -> Any:
    if payload is None:
        return "missing"
    return payload.get(key, "missing")


def _mapping_or_none(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


def _load_optional_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_last_jsonl(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    payload = json.loads(lines[-1])
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} last line must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
