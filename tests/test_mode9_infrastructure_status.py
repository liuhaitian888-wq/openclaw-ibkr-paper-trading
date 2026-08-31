import unittest

from scripts.build_mode9_infrastructure_status import (
    REQUIRED_TABLES,
    build_sqlite_audit,
    ensure_sqlite_tables,
    feature_status,
)


class Mode9InfrastructureStatusTests(unittest.TestCase):
    def test_feature_status_schema_contains_required_fields(self) -> None:
        row = feature_status("execution_writer_lock", {"lock_owner": {"process_name": "mode9_autonomous_agent"}}, True)
        for key in [
            "feature_name",
            "implementation_state",
            "execution_state",
            "trigger_state",
            "blocked_reason",
            "report_path",
            "remaining_gap",
        ]:
            self.assertIn(key, row)

    def test_sqlite_tables_exist_after_ensure(self) -> None:
        ensure_sqlite_tables()
        report = build_sqlite_audit()
        for table in REQUIRED_TABLES:
            self.assertTrue(report["tables"][table]["table_exists"])


if __name__ == "__main__":
    unittest.main()
