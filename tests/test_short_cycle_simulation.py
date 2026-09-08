import json
import tempfile
import unittest
from pathlib import Path

from trading.short_cycle_simulation import run_short_cycle_simulation


class ShortCycleSimulationTests(unittest.TestCase):
    def test_offline_rehearsal_reuses_pool_risk_audit_and_restart_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            summary = run_short_cycle_simulation(output, cycles=8)

            self.assertEqual(summary["result"], "PASS")
            self.assertEqual(summary["paper_orders_submitted"], 0)
            self.assertTrue(summary["restart_recovery_verified"])
            self.assertGreater(summary["canonical_transition_count"], 0)
            self.assertEqual(summary["timeline_event_count"], summary["event_store_count"])
            self.assertTrue((output / "short_cycle_audit.sqlite3").exists())
            self.assertTrue((output / "replay_query.sql").exists())
            events = [json.loads(line) for line in (output / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(event["event_type"] == "SAFE_MODE" for event in events))
            self.assertTrue(any(event["source_module"] == "RESTART_RECOVERY" for event in events))
