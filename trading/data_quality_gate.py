"""Fail-safe market-data quality gate used before new Paper risk is created."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from trading.pool_state import quote_readiness


@dataclass(frozen=True)
class DataQualityDecision:
    state: str
    allow_new_risk: bool
    severity: str
    reason_code: str
    recovery_required: bool


class DataQualityGate:
    """Stateful gate: an incident needs consecutive fresh observations to clear."""

    def __init__(self, *, recovery_fresh_observations: int = 2) -> None:
        if recovery_fresh_observations < 1:
            raise ValueError("recovery_fresh_observations must be at least one")
        self._required = recovery_fresh_observations
        self._fresh_count = 0
        self._incident_open = False

    def evaluate(self, quote: Mapping[str, Any] | None, *, now: str, api_error: str = "") -> DataQualityDecision:
        if api_error:
            return self._fail("API_ERROR", "CRITICAL")
        if not quote:
            return self._fail("EMPTY_DATA", "CRITICAL")
        readiness = quote_readiness(quote, quote_freshness_sec=5.0, max_spread_pct=0.01, now=now)
        if not readiness["ready"]:
            reason = str(readiness["reason_code"])
            severity = "CRITICAL" if reason in {"MISSING_BID", "MISSING_ASK", "STALE_ASK"} else "WARNING"
            return self._fail(reason, severity)
        self._fresh_count += 1
        if self._incident_open and self._fresh_count < self._required:
            return DataQualityDecision("RECOVERING", False, "WARNING", "RECOVERY_FRESHNESS_PENDING", True)
        self._incident_open = False
        return DataQualityDecision("HEALTHY", True, "INFO", "", False)

    def _fail(self, reason_code: str, severity: str) -> DataQualityDecision:
        self._incident_open = True
        self._fresh_count = 0
        return DataQualityDecision("SAFE_MODE", False, severity, reason_code, True)
