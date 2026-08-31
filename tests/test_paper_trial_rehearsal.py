import tempfile
import unittest
from pathlib import Path

from research.paper_trial_rehearsal import run_rehearsal


class PaperTrialRehearsalTests(unittest.TestCase):
    def test_rehearsal_runs_ready_path_without_ibkr_or_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = run_rehearsal(["AAPL"], output_dir=output_dir)

            self.assertEqual(report.mode, "simulated_rehearsal")
            self.assertEqual(report.status, "completed")
            self.assertEqual(report.guarded_session_status, "validate_required")
            self.assertFalse(report.ibkr_market_data_used)
            self.assertFalse(report.trading_api_validate_used)
            self.assertFalse(report.paper_order_used)
            self.assertTrue((output_dir / "quotes.csv").exists())
            self.assertTrue((output_dir / "paper_trial_rehearsal.json").exists())


if __name__ == "__main__":
    unittest.main()
