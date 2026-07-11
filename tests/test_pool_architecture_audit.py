import unittest

from scripts.build_pool_architecture_audit import build_reports


class PoolArchitectureAuditTests(unittest.TestCase):
    def test_audit_reports_six_layer_runtime_wired_but_execution_gated(self) -> None:
        architecture, membership, audit = build_reports()
        self.assertIn("security_master", [layer["pool_name"] for layer in architecture["layers"]])
        self.assertTrue(architecture["answers"]["Mode 9 consumes pool_manager output"])
        self.assertFalse(architecture["answers"]["Mode 9 consumes pool_manager output for execution"])
        self.assertTrue(architecture["answers"]["Mode 9 uses data/us_equity_universe.csv directly"])
        self.assertTrue(membership["records"])
        self.assertIn("trading/security_master.py exists", audit["answers"])


if __name__ == "__main__":
    unittest.main()
