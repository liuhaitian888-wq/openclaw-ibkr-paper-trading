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

from trading.audit import AuditLog
from trading.config import Settings


SUBMITTED_GATE_STATUS = "submitted"
SUCCESS_AUDIT_STATUSES = {
    "PAPER_SUBMITTED",
    "PAPER_LIMIT_SUBMITTED",
    "PAPER_PENDING_CONFIRMATION",
    "PAPER_LIMIT_PENDING_CONFIRMATION",
}


@dataclass(frozen=True)
class ReconciliationItem:
    name: str
    status: str
    required: bool
    detail: str


@dataclass(frozen=True)
class PaperTrialReconciliationReport:
    source: str
    created_at: str
    status: str
    reason: str
    idempotency_key: Optional[str]
    selected_symbol: Optional[str]
    items: list[ReconciliationItem] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


def build_reconciliation(
    execution_gate: Optional[Mapping[str, Any]],
    *,
    audit_order: Optional[Mapping[str, Any]] = None,
    tws_orders: Optional[Mapping[str, Any]] = None,
    pnl_sample: Optional[Mapping[str, Any]] = None,
    artifacts: Optional[Mapping[str, str]] = None,
) -> PaperTrialReconciliationReport:
    if execution_gate is None:
        return _report(
            status="no_paper_submission",
            reason="paper execution gate report is missing",
            idempotency_key=None,
            selected_symbol=None,
            items=[
                ReconciliationItem(
                    "execution_gate",
                    "missing",
                    False,
                    "no paper execution gate report was available",
                )
            ],
            artifacts=artifacts,
        )

    payload = execution_gate.get("selected_payload")
    if not isinstance(payload, Mapping):
        payload = {}
    idempotency_key = _optional_str(payload.get("idempotency_key"))
    selected_symbol = _optional_str(execution_gate.get("selected_symbol") or payload.get("symbol"))
    gate_status = str(execution_gate.get("status", "unknown"))
    if gate_status != SUBMITTED_GATE_STATUS:
        return _report(
            status="no_paper_submission",
            reason=f"paper execution gate status is {gate_status}",
            idempotency_key=idempotency_key,
            selected_symbol=selected_symbol,
            items=[
                ReconciliationItem(
                    "execution_gate_submitted",
                    "not_applicable",
                    False,
                    f"gate status={gate_status}",
                )
            ],
            artifacts=artifacts,
        )

    items = [
        ReconciliationItem(
            "execution_gate_submitted",
            "pass",
            True,
            "paper execution gate reported submitted",
        ),
        _audit_item(audit_order, idempotency_key),
        _tws_order_item(tws_orders, idempotency_key),
        _pnl_item(pnl_sample),
    ]
    failures = [item for item in items if item.required and item.status == "fail"]
    warnings = [item for item in items if item.required and item.status in {"missing", "unknown"}]
    if failures:
        status = "reconciliation_failed"
        reason = "one or more required paper-order reconciliation checks failed"
    elif warnings:
        status = "reconciliation_incomplete"
        reason = "paper order was submitted, but one or more readback artifacts are missing"
    else:
        status = "reconciled"
        reason = "paper order submission is present in gate, audit, TWS readback, and P&L snapshot"
    return _report(
        status=status,
        reason=reason,
        idempotency_key=idempotency_key,
        selected_symbol=selected_symbol,
        items=items,
        artifacts=artifacts,
    )


def write_reconciliation(report: PaperTrialReconciliationReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a post-paper-trial reconciliation report from execution gate, audit, TWS, and P&L readbacks."
    )
    parser.add_argument("--execution-gate", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--tws-orders-json", type=Path, default=PROJECT_ROOT / "reports" / "tws_orders_snapshot.json")
    parser.add_argument("--pnl-jsonl", type=Path, default=PROJECT_ROOT / "reports" / "pnl_timeseries.jsonl")
    parser.add_argument("--audit-db", type=Path)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_reconciliation.json")
    args = parser.parse_args()

    settings = Settings.load()
    execution_gate = _load_optional_json_object(args.execution_gate)
    idempotency_key = _idempotency_from_gate(execution_gate)
    audit_order = _load_audit_order(args.audit_db or settings.audit_db, idempotency_key)
    tws_orders = _load_optional_json_object(args.tws_orders_json)
    pnl_sample = _load_latest_jsonl(args.pnl_jsonl)
    report = build_reconciliation(
        execution_gate,
        audit_order=audit_order,
        tws_orders=tws_orders,
        pnl_sample=pnl_sample,
        artifacts={
            "execution_gate": str(args.execution_gate),
            "tws_orders_json": str(args.tws_orders_json),
            "pnl_jsonl": str(args.pnl_jsonl),
            "audit_db": str(args.audit_db or settings.audit_db),
            "output": str(args.output),
        },
    )
    write_reconciliation(report, args.output)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _audit_item(audit_order: Optional[Mapping[str, Any]], idempotency_key: Optional[str]) -> ReconciliationItem:
    if not idempotency_key:
        return ReconciliationItem("audit_record", "fail", True, "selected payload has no idempotency_key")
    if audit_order is None:
        return ReconciliationItem("audit_record", "missing", True, f"no audit record found for {idempotency_key}")
    order = audit_order.get("order", audit_order)
    if not isinstance(order, Mapping):
        return ReconciliationItem("audit_record", "fail", True, "audit payload is not an order object")
    status = str(order.get("status", ""))
    if status in SUCCESS_AUDIT_STATUSES:
        return ReconciliationItem("audit_record", "pass", True, f"audit status={status}")
    return ReconciliationItem("audit_record", "fail", True, f"audit status={status or 'unknown'}")


def _tws_order_item(tws_orders: Optional[Mapping[str, Any]], idempotency_key: Optional[str]) -> ReconciliationItem:
    if tws_orders is None:
        return ReconciliationItem("tws_order_readback", "missing", True, "TWS orders snapshot is missing")
    if tws_orders.get("status") not in {None, "ok"}:
        return ReconciliationItem("tws_order_readback", "fail", True, f"TWS snapshot status={tws_orders.get('status')}")
    if not idempotency_key:
        return ReconciliationItem("tws_order_readback", "fail", True, "selected payload has no idempotency_key")
    if _tws_snapshot_contains_key(tws_orders, idempotency_key):
        return ReconciliationItem("tws_order_readback", "pass", True, f"TWS readback contains order_ref or execution for {idempotency_key}")
    return ReconciliationItem("tws_order_readback", "fail", True, f"TWS readback does not contain {idempotency_key}")


def _pnl_item(pnl_sample: Optional[Mapping[str, Any]]) -> ReconciliationItem:
    if pnl_sample is None:
        return ReconciliationItem("pnl_snapshot", "missing", True, "P&L snapshot is missing")
    account = pnl_sample.get("account", "")
    open_positions = pnl_sample.get("open_positions", "unknown")
    return ReconciliationItem(
        "pnl_snapshot",
        "pass",
        True,
        f"account={account}; open_positions={open_positions}; timestamp={pnl_sample.get('timestamp', '')}",
    )


def _tws_snapshot_contains_key(tws_orders: Mapping[str, Any], idempotency_key: str) -> bool:
    containers = [
        tws_orders.get("open_orders", []),
        tws_orders.get("completed_orders", []),
        tws_orders.get("executions", []),
    ]
    for container in containers:
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, Mapping):
                continue
            if item.get("order_ref") == idempotency_key:
                return True
            if idempotency_key in json.dumps(item, sort_keys=True):
                return True
    return False


def _report(
    *,
    status: str,
    reason: str,
    idempotency_key: Optional[str],
    selected_symbol: Optional[str],
    items: list[ReconciliationItem],
    artifacts: Optional[Mapping[str, str]],
) -> PaperTrialReconciliationReport:
    return PaperTrialReconciliationReport(
        source="paper_trial_reconciliation",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        reason=reason,
        idempotency_key=idempotency_key,
        selected_symbol=selected_symbol,
        items=items,
        artifacts={} if artifacts is None else dict(artifacts),
    )


def _idempotency_from_gate(execution_gate: Optional[Mapping[str, Any]]) -> Optional[str]:
    if execution_gate is None:
        return None
    payload = execution_gate.get("selected_payload")
    if not isinstance(payload, Mapping):
        return None
    return _optional_str(payload.get("idempotency_key"))


def _load_audit_order(audit_db: Path, idempotency_key: Optional[str]) -> Optional[Mapping[str, Any]]:
    if not idempotency_key or not audit_db.exists():
        return None
    order = AuditLog(audit_db).get(idempotency_key)
    if order is None:
        return None
    return {"status": "ok", "order": order}


def _load_optional_json_object(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_latest_jsonl(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    last = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    if not last:
        return None
    payload = json.loads(last)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain JSON objects")
    return payload


def _optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


if __name__ == "__main__":
    raise SystemExit(main())
