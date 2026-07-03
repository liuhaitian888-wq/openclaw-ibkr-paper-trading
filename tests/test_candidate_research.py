from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from trading.candidate_research import (
    CandidateDraft,
    EvidenceItem,
    HardAuditConfig,
    LlmPreReview,
    build_candidate_report,
)
from trading.market_data import Quote
from trading.strategy import CandidateProfile
from trading.universe import load_universe
from scripts.approve_candidate_to_universe import upsert_candidate


class CandidateResearchTests(unittest.TestCase):
    def test_hard_audit_approves_structured_candidate(self) -> None:
        draft = candidate("ZZTOP")
        report = build_candidate_report(
            draft,
            existing_universe=load_universe(),
            config=HardAuditConfig(),
            quote=Quote(
                symbol="ZZTOP",
                last=100.0,
                bid=99.98,
                ask=100.02,
                timestamp=datetime.now(timezone.utc),
                source="ibkr_readonly",
            ),
            contract_verified=True,
        )

        self.assertTrue(report.hard_audit.approved)
        self.assertEqual(report.symbol, "ZZTOP")

    def test_hard_audit_rejects_low_confidence(self) -> None:
        draft = candidate("ZZLOW", confidence=0.2)
        report = build_candidate_report(
            draft,
            existing_universe=load_universe(),
            config=HardAuditConfig(require_realtime_quote=False, require_contract_verified=False),
        )

        self.assertFalse(report.hard_audit.approved)
        self.assertIn("LLM confidence below threshold", report.hard_audit.reasons)

    def test_hard_audit_rejects_existing_universe_symbol(self) -> None:
        report = build_candidate_report(
            candidate("AAPL"),
            existing_universe=load_universe(),
            config=HardAuditConfig(require_realtime_quote=False, require_contract_verified=False),
        )

        self.assertFalse(report.hard_audit.approved)
        self.assertIn("symbol already exists in universe", report.hard_audit.reasons)

    def test_approval_upserts_candidate_row(self) -> None:
        report = build_candidate_report(
            candidate("ZZAPP"),
            existing_universe=load_universe(),
            config=HardAuditConfig(),
            quote=Quote(
                symbol="ZZAPP",
                last=100.0,
                bid=99.98,
                ask=100.02,
                timestamp=datetime.now(timezone.utc),
                source="ibkr_readonly",
            ),
            contract_verified=True,
        )

        rows = upsert_candidate([], report, "rules")

        self.assertEqual(rows[0]["symbol"], "ZZAPP")
        self.assertEqual(rows[0]["enabled"], "true")
        self.assertIn("llm-reviewed", rows[0]["tags"])


def candidate(symbol: str, confidence: float = 0.75) -> CandidateDraft:
    return CandidateDraft(
        symbol=symbol,
        name=f"{symbol} Corp",
        exchange="NASDAQ",
        sector="Technology",
        tags=("software",),
        profile=CandidateProfile(
            symbol=symbol,
            pe_ratio=18.0,
            forward_pe=16.0,
            peg_ratio=1.1,
            debt_to_equity=0.3,
            revenue_growth_yoy=0.12,
            gross_margin=0.65,
            operating_margin=0.24,
            return_on_invested_capital=0.2,
            free_cash_flow_positive=True,
            earnings_positive=True,
            analyst_revision_positive=True,
            average_volume=5_000_000,
        ),
        pre_review=LlmPreReview(
            model="test-llm",
            thesis="Strong quality and trend candidate.",
            proposed_action="ADD",
            confidence=confidence,
            bull_case=("margin expansion",),
            bear_case=("valuation risk",),
            catalysts=("earnings",),
            risks=("competition",),
        ),
        evidence=(
            EvidenceItem(source="sec", title="10-Q", summary="fundamentals"),
            EvidenceItem(source="news", title="News", summary="catalyst"),
        ),
    )


if __name__ == "__main__":
    unittest.main()
