import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from trading.market_data import Quote
from trading.strategy import CandidateProfile, ValueFilterConfig, ValuePoolFilter
from trading.universe import UniverseEntry


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    title: str = ""
    url: str = ""
    published_at: str = ""
    summary: str = ""


@dataclass(frozen=True)
class LlmPreReview:
    model: str
    thesis: str
    proposed_action: str
    confidence: float
    bull_case: Tuple[str, ...] = ()
    bear_case: Tuple[str, ...] = ()
    catalysts: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateDraft:
    symbol: str
    name: str = ""
    exchange: str = ""
    sector: str = ""
    tags: Tuple[str, ...] = ()
    profile: Optional[CandidateProfile] = None
    pre_review: Optional[LlmPreReview] = None
    evidence: Tuple[EvidenceItem, ...] = ()


@dataclass(frozen=True)
class HardAuditConfig:
    min_llm_confidence: float = 0.6
    min_evidence_items: int = 2
    min_value_score: float = 45.0
    min_average_volume: int = 1_000_000
    max_quote_age_ms: float = 10_000.0
    max_spread_pct: float = 0.003
    require_contract_verified: bool = True
    require_realtime_quote: bool = True


@dataclass(frozen=True)
class HardAuditResult:
    approved: bool
    reasons: Tuple[str, ...]
    checks: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateReport:
    symbol: str
    created_at: str
    draft: CandidateDraft
    hard_audit: HardAuditResult

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def build_candidate_report(
    draft: CandidateDraft,
    *,
    existing_universe: Sequence[UniverseEntry],
    config: HardAuditConfig = HardAuditConfig(),
    quote: Optional[Quote] = None,
    contract_verified: bool = False,
) -> CandidateReport:
    return CandidateReport(
        symbol=draft.symbol.upper(),
        created_at=datetime.now(timezone.utc).isoformat(),
        draft=normalize_draft(draft),
        hard_audit=audit_candidate(
            normalize_draft(draft),
            existing_universe=existing_universe,
            config=config,
            quote=quote,
            contract_verified=contract_verified,
        ),
    )


def audit_candidate(
    draft: CandidateDraft,
    *,
    existing_universe: Sequence[UniverseEntry],
    config: HardAuditConfig = HardAuditConfig(),
    quote: Optional[Quote] = None,
    contract_verified: bool = False,
) -> HardAuditResult:
    reasons: List[str] = []
    checks: Dict[str, object] = {}
    symbol = draft.symbol.upper()
    existing_symbols = {entry.symbol.upper() for entry in existing_universe}
    checks["already_in_universe"] = symbol in existing_symbols
    if not symbol:
        reasons.append("symbol is required")
    if symbol in existing_symbols:
        reasons.append("symbol already exists in universe")

    pre_review = draft.pre_review
    if pre_review is None:
        reasons.append("LLM pre-review is required")
    else:
        checks["llm_confidence"] = pre_review.confidence
        if pre_review.confidence < config.min_llm_confidence:
            reasons.append("LLM confidence below threshold")
        if not pre_review.thesis.strip():
            reasons.append("LLM thesis is required")
        if pre_review.proposed_action.upper() not in {"ADD", "WATCHLIST"}:
            reasons.append("LLM proposed_action must be ADD or WATCHLIST")

    checks["evidence_count"] = len(draft.evidence)
    if len(draft.evidence) < config.min_evidence_items:
        reasons.append("not enough evidence items")
    if any(not item.source.strip() for item in draft.evidence):
        reasons.append("each evidence item requires a source")

    if draft.profile is None:
        reasons.append("fundamental profile is required for hard audit")
    else:
        value_filter = ValuePoolFilter(
            ValueFilterConfig(
                min_score=config.min_value_score,
                min_average_volume=config.min_average_volume,
            )
        )
        value_result = value_filter.evaluate(draft.profile)
        checks["value_score"] = value_result.score
        checks["value_score_breakdown"] = value_result.score_breakdown
        if not value_result.approved:
            reasons.extend(value_result.reasons)

    checks["contract_verified"] = contract_verified
    if config.require_contract_verified and not contract_verified:
        reasons.append("TWS contract has not been verified")

    checks["quote_verified"] = quote is not None
    if config.require_realtime_quote and quote is None:
        reasons.append("real-time IBKR quote is required")
    if quote is not None:
        checks["quote"] = {
            "symbol": quote.symbol,
            "last": quote.last,
            "bid": quote.bid,
            "ask": quote.ask,
            "spread": quote.spread,
            "age_ms": quote.age_ms(),
            "source": quote.source,
            "timestamp": quote.timestamp.isoformat(),
        }
        if quote.symbol.upper() != symbol:
            reasons.append("quote symbol does not match candidate")
        if quote.age_ms() > config.max_quote_age_ms:
            reasons.append("real-time quote is stale")
        if quote.spread is None:
            reasons.append("real-time quote must include bid/ask spread")
        elif quote.last > 0 and quote.spread / quote.last > config.max_spread_pct:
            reasons.append("real-time quote spread is too wide")

    return HardAuditResult(not reasons, tuple(dict.fromkeys(reasons)), checks)


def normalize_draft(draft: CandidateDraft) -> CandidateDraft:
    return CandidateDraft(
        symbol=draft.symbol.strip().upper(),
        name=draft.name.strip(),
        exchange=draft.exchange.strip().upper(),
        sector=draft.sector.strip(),
        tags=tuple(dict.fromkeys(tag.strip() for tag in draft.tags if tag.strip())),
        profile=draft.profile,
        pre_review=draft.pre_review,
        evidence=draft.evidence,
    )


def load_candidate_draft(path: Path) -> CandidateDraft:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("candidate draft must be a JSON object")
    return candidate_draft_from_dict(payload)


def candidate_draft_from_dict(payload: Dict[str, object]) -> CandidateDraft:
    profile_payload = payload.get("profile")
    pre_review_payload = payload.get("pre_review")
    evidence_payload = payload.get("evidence", [])
    return CandidateDraft(
        symbol=str(payload.get("symbol", "")),
        name=str(payload.get("name", "")),
        exchange=str(payload.get("exchange", "")),
        sector=str(payload.get("sector", "")),
        tags=_tuple_of_strings(payload.get("tags", [])),
        profile=_profile_from_dict(profile_payload) if isinstance(profile_payload, dict) else None,
        pre_review=_pre_review_from_dict(pre_review_payload) if isinstance(pre_review_payload, dict) else None,
        evidence=tuple(
            _evidence_from_dict(item)
            for item in evidence_payload
            if isinstance(item, dict)
        )
        if isinstance(evidence_payload, list)
        else (),
    )


def write_candidate_report(report: CandidateReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / (
        f"candidate_{report.symbol.lower()}_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def candidate_report_from_dict(payload: Dict[str, object]) -> CandidateReport:
    hard_payload = payload.get("hard_audit")
    if not isinstance(hard_payload, dict):
        raise ValueError("candidate report requires hard_audit")
    return CandidateReport(
        symbol=str(payload.get("symbol", "")),
        created_at=str(payload.get("created_at", "")),
        draft=candidate_draft_from_dict(payload.get("draft", {}) if isinstance(payload.get("draft"), dict) else {}),
        hard_audit=HardAuditResult(
            approved=bool(hard_payload.get("approved")),
            reasons=_tuple_of_strings(hard_payload.get("reasons", [])),
            checks=hard_payload.get("checks", {}) if isinstance(hard_payload.get("checks"), dict) else {},
        ),
    )


def load_candidate_report(path: Path) -> CandidateReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("candidate report must be a JSON object")
    return candidate_report_from_dict(payload)


def _profile_from_dict(payload: Dict[str, object]) -> CandidateProfile:
    return CandidateProfile(
        symbol=str(payload.get("symbol", "")),
        pe_ratio=_float_or_none(payload.get("pe_ratio")),
        forward_pe=_float_or_none(payload.get("forward_pe")),
        peg_ratio=_float_or_none(payload.get("peg_ratio")),
        price_to_free_cash_flow=_float_or_none(payload.get("price_to_free_cash_flow")),
        debt_to_equity=_float_or_none(payload.get("debt_to_equity")),
        revenue_growth_yoy=_float_or_none(payload.get("revenue_growth_yoy")),
        gross_margin=_float_or_none(payload.get("gross_margin")),
        operating_margin=_float_or_none(payload.get("operating_margin")),
        return_on_invested_capital=_float_or_none(payload.get("return_on_invested_capital")),
        free_cash_flow_positive=_bool_or_true(payload.get("free_cash_flow_positive")),
        earnings_positive=_bool_or_true(payload.get("earnings_positive")),
        analyst_revision_positive=_bool_or_none(payload.get("analyst_revision_positive")),
        average_volume=_int_or_none(payload.get("average_volume")),
    )


def _pre_review_from_dict(payload: Dict[str, object]) -> LlmPreReview:
    return LlmPreReview(
        model=str(payload.get("model", "")),
        thesis=str(payload.get("thesis", "")),
        proposed_action=str(payload.get("proposed_action", "")),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        bull_case=_tuple_of_strings(payload.get("bull_case", [])),
        bear_case=_tuple_of_strings(payload.get("bear_case", [])),
        catalysts=_tuple_of_strings(payload.get("catalysts", [])),
        risks=_tuple_of_strings(payload.get("risks", [])),
    )


def _evidence_from_dict(payload: Dict[str, object]) -> EvidenceItem:
    return EvidenceItem(
        source=str(payload.get("source", "")),
        title=str(payload.get("title", "")),
        url=str(payload.get("url", "")),
        published_at=str(payload.get("published_at", "")),
        summary=str(payload.get("summary", "")),
    )


def _tuple_of_strings(value: object) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _float_or_none(value: object) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool_or_true(value: object) -> bool:
    if value is None or value == "":
        return True
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _bool_or_none(value: object) -> Optional[bool]:
    if value is None or value == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}
