import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.models import TradeProposal


REPORT_DIR = PROJECT_ROOT / "reports" / "order_rejections"


def log_order_rejection(
    *,
    proposal: TradeProposal,
    error: Exception | str,
    runtime_cycle_id: str | None = None,
    action_taken: str = "logged_rejection_no_retry",
    retry_allowed: bool = False,
    retry_performed: bool = False,
    normalized_price: float | None = None,
) -> dict[str, Any]:
    message = str(error)
    code, ib_message = _parse_ib_error(message)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": proposal.symbol,
        "side": proposal.side,
        "order_type": "BRACKET" if proposal.stop_price is not None else "LMT",
        "quantity": proposal.quantity,
        "limit_price": proposal.limit_price,
        "stop_price": proposal.stop_price,
        "normalized_price": normalized_price,
        "ib_error_code": code,
        "ib_error_message": ib_message or message,
        "local_plan_id": proposal.idempotency_key,
        "runtime_cycle_id": runtime_cycle_id,
        "action_taken": action_taken,
        "retry_allowed": retry_allowed,
        "retry_performed": retry_performed,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def rejection_result(
    *,
    proposal: TradeProposal,
    error: Exception | str,
    runtime_cycle_id: str | None = None,
) -> Mapping[str, Any]:
    report = log_order_rejection(
        proposal=proposal,
        error=error,
        runtime_cycle_id=runtime_cycle_id,
    )
    return {
        "status": "REJECTED",
        "approved": False,
        "workflow_step": "order_rejection",
        "reason": report["ib_error_message"],
        "order_rejection_report": str(REPORT_DIR / "latest.json"),
    }


def _parse_ib_error(message: str) -> tuple[int | None, str | None]:
    match = re.search(r",\s*(\d+),\s*'([^']+)'", message)
    if not match:
        return None, None
    return int(match.group(1)), match.group(2)
