"""Run the guarded IBKR paper-trial session workflow."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.guarded_paper_trial_session import main


if __name__ == "__main__":
    raise SystemExit(main())
