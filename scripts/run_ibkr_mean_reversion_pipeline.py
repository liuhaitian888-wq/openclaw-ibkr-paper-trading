"""Record read-only IBKR quotes and run mean-reversion diagnostics."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.ibkr_mean_reversion_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
