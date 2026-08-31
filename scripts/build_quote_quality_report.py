"""Build a quote quality report from recorded IBKR quote samples."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.quote_quality_report import main


if __name__ == "__main__":
    raise SystemExit(main())
