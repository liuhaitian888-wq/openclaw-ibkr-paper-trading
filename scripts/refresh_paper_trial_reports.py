"""Refresh all paper-trial reports in safe order."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.paper_trial_report_refresh import main


if __name__ == "__main__":
    raise SystemExit(main())
