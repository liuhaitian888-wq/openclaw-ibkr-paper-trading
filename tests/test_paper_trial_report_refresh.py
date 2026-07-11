import tempfile
import unittest
from pathlib import Path

from research.paper_trial_report_refresh import PaperTrialReportRefreshConfig, refresh_reports
from tests.test_paper_environment_audit import make_settings
from trading.audit import AuditLog
from trading.models import TradeProposal


class FailingQuoteSource:
    last_errors: list[str] = []

    def get_quotes(self, symbols: list[str]) -> list[object]:
        raise AssertionError("quote source must not be used when environment is blocked")


class PaperTrialReportRefreshTests(unittest.TestCase):
    def test_refresh_blocked_environment_writes_reports_without_quote_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = PaperTrialReportRefreshConfig(
                symbols=["AAPL"],
                samples=1,
                interval_seconds=0.0,
                quotes_csv=root / "quotes.csv",
                recorder_report=root / "recorder.json",
                diagnostics_report=root / "diagnostics.json",
                paper_plan_report=root / "plan.json",
                ibkr_pipeline_report=root / "pipeline.json",
                readiness_report=root / "readiness.json",
                execution_gate_report=root / "gate.json",
                full_pipeline_report=root / "full.json",
                environment_audit_report=root / "environment.json",
                guarded_session_report=root / "guarded.json",
                reconciliation_report=root / "reconciliation.json",
                tws_orders_json=root / "orders.json",
                pnl_jsonl=root / "pnl.jsonl",
                runbook_json=root / "runbook.json",
                runbook_md=root / "runbook.md",
                status_html=root / "status.html",
                evidence_json=root / "evidence.json",
                evidence_md=root / "evidence.md",
                rehearsal_report=root / "rehearsal.json",
                preflight_json=root / "preflight.json",
                preflight_md=root / "preflight.md",
                strategy_catalog_json=root / "strategy_catalog.json",
                readiness_monitor_json=root / "monitor.json",
                completion_audit_json=root / "completion.json",
                completion_audit_md=root / "completion.md",
            )

            report = refresh_reports(
                make_settings(tmp),
                config,
                health=None,
                api_error="connection refused",
                quote_source_factory=lambda: FailingQuoteSource(),
            )

            self.assertEqual(report.status, "refreshed_blocked")
            self.assertEqual(report.evidence_stage, "blocked_before_paper_window")
            self.assertFalse((root / "quotes.csv").exists())
            for name in [
                "environment.json",
                "guarded.json",
                "reconciliation.json",
                "runbook.json",
                "runbook.md",
                "status.html",
                "evidence.json",
                "evidence.md",
                "preflight.json",
                "preflight.md",
                "completion.json",
                "completion.md",
            ]:
                self.assertTrue((root / name).exists(), name)

    def test_refresh_reads_audit_record_for_submitted_gate_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(tmp)
            audit = AuditLog(settings.audit_db)
            proposal = TradeProposal("AAPL", "BUY", 1, 100.0, None, "paper-aapl-0001")
            self.assertTrue(audit.reserve(proposal, "PAPER_LIMIT_TRANSMIT", "test"))
            audit.update("paper-aapl-0001", "PAPER_LIMIT_SUBMITTED", "submitted")

            gate = root / "gate.json"
            gate.write_text(
                """
                {
                  "status": "submitted",
                  "selected_symbol": "AAPL",
                  "selected_payload": {
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": 1,
                    "limit_price": 100.0,
                    "idempotency_key": "paper-aapl-0001"
                  }
                }
                """,
                encoding="utf-8",
            )
            (root / "orders.json").write_text(
                '{"status":"ok","open_orders":[{"order_ref":"paper-aapl-0001"}],"completed_orders":[],"executions":[]}',
                encoding="utf-8",
            )
            (root / "pnl.jsonl").write_text(
                '{"timestamp":"2026-07-07T23:00:00+00:00","account":"DU12345","open_positions":1}\n',
                encoding="utf-8",
            )
            config = PaperTrialReportRefreshConfig(
                symbols=["AAPL"],
                samples=1,
                interval_seconds=0.0,
                execution_gate_report=gate,
                environment_audit_report=root / "environment.json",
                guarded_session_report=root / "guarded.json",
                reconciliation_report=root / "reconciliation.json",
                tws_orders_json=root / "orders.json",
                pnl_jsonl=root / "pnl.jsonl",
                runbook_json=root / "runbook.json",
                runbook_md=root / "runbook.md",
                status_html=root / "status.html",
                evidence_json=root / "evidence.json",
                evidence_md=root / "evidence.md",
                rehearsal_report=root / "rehearsal.json",
                preflight_json=root / "preflight.json",
                preflight_md=root / "preflight.md",
                strategy_catalog_json=root / "strategy_catalog.json",
                readiness_monitor_json=root / "monitor.json",
                completion_audit_json=root / "completion.json",
                completion_audit_md=root / "completion.md",
            )

            report = refresh_reports(
                settings,
                config,
                health=None,
                api_error="connection refused",
                quote_source_factory=lambda: FailingQuoteSource(),
            )

            self.assertEqual(report.reconciliation_status, "reconciled")
            reconciliation = (root / "reconciliation.json").read_text(encoding="utf-8")
            self.assertIn("audit status=PAPER_LIMIT_SUBMITTED", reconciliation)
            completion = (root / "completion.json").read_text(encoding="utf-8")
            self.assertIn("incomplete_real_ibkr_evidence_missing", completion)


if __name__ == "__main__":
    unittest.main()
