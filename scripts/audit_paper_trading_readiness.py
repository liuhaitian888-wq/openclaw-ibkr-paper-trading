"""Audit local readiness for a one-share IBKR paper trial."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.paper_environment_audit import main


if __name__ == "__main__":
    raise SystemExit(main())
