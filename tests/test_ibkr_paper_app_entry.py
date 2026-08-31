import plistlib
import tempfile
import unittest
from pathlib import Path

from scripts.ibkr_paper_app_entry import (
    LABEL,
    build_launch_agent,
    inspect_status,
    process_is_running,
)


class IbkrPaperAppEntryTests(unittest.TestCase):
    def test_process_detection_uses_tws_markers(self) -> None:
        self.assertTrue(
            process_is_running(
                ["/Users/test/Applications/Trader Workstation/Trader Workstation.app/Contents/MacOS/JavaApplicationStub"]
            )
        )
        self.assertFalse(process_is_running(["/usr/bin/python3 api_service.py"]))

    def test_status_distinguishes_open_login_from_ready_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Trader Workstation.app"
            app.mkdir()
            agent = Path(tmp) / "agent.plist"
            status = inspect_status(
                app,
                7497,
                process_lines=[f"{app}/Contents/MacOS/Trader Workstation"],
                port_reachable=False,
                agent_path=agent,
            )
            self.assertEqual(status.state, "TWS_OPEN_LOGIN_OR_API_NOT_READY")

            ready = inspect_status(
                app,
                7497,
                process_lines=[],
                port_reachable=True,
                agent_path=agent,
            )
            self.assertEqual(ready.state, "PAPER_API_PORT_REACHABLE")

    def test_launch_agent_is_standard_library_and_paper_only(self) -> None:
        payload = build_launch_agent(
            Path("/project/scripts/ibkr_paper_app_entry.py"),
            Path("/Applications/Trader Workstation.app"),
            7497,
            Path("/project/.runtime/logs"),
        )
        encoded = plistlib.dumps(payload)
        decoded = plistlib.loads(encoded)
        self.assertEqual(decoded["Label"], LABEL)
        self.assertIn("7497", decoded["ProgramArguments"])
        self.assertNotIn("7496", decoded["ProgramArguments"])
        self.assertNotIn("password", encoded.decode("utf-8").lower())
        self.assertNotIn("api_service.py", encoded.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
