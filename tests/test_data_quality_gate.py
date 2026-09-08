import unittest

from trading.data_quality_gate import DataQualityGate


NOW = "2026-08-31T13:30:00+00:00"
QUOTE = {"bid": 100.0, "ask": 100.2, "last": 100.1, "timestamp": NOW}


class DataQualityGateTests(unittest.TestCase):
    def test_failure_blocks_new_risk_and_two_fresh_updates_are_required_to_recover(self) -> None:
        gate = DataQualityGate(recovery_fresh_observations=2)

        failure = gate.evaluate(None, now=NOW)
        first = gate.evaluate(QUOTE, now=NOW)
        recovered = gate.evaluate(QUOTE, now=NOW)

        self.assertEqual(failure.state, "SAFE_MODE")
        self.assertFalse(failure.allow_new_risk)
        self.assertEqual(first.state, "RECOVERING")
        self.assertFalse(first.allow_new_risk)
        self.assertEqual(recovered.state, "HEALTHY")
        self.assertTrue(recovered.allow_new_risk)

    def test_stale_or_api_error_blocks_new_risk(self) -> None:
        gate = DataQualityGate()

        stale = gate.evaluate({**QUOTE, "timestamp": "2026-08-31T13:29:00+00:00"}, now=NOW)
        api = gate.evaluate(QUOTE, now=NOW, api_error="connection lost")

        self.assertEqual(stale.reason_code, "STALE_ASK")
        self.assertEqual(api.reason_code, "API_ERROR")
        self.assertFalse(api.allow_new_risk)
