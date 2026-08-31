"""Run the full read-only-to-paper-gate trial pipeline."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.full_paper_trial_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
