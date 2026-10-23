"""Persistent production paths. Importing this module never creates files.

OPENCLAW_STATE_DIR is for isolated tests/development. Production startup also
checks an approved deployment manifest and rejects a repository-owned state root.
"""
import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_WORKSPACE = (Path('/opt/openclaw/app') if sys.platform == 'linux'
                        else Path.home() / 'Documents' / 'New project')
STATE_ROOT = Path(os.environ.get('OPENCLAW_STATE_DIR', str(Path.home() / '.local/state/openclaw'))).expanduser()
if not STATE_ROOT.is_absolute():
    raise ValueError('OPENCLAW_STATE_DIR must be absolute, never relative to cwd')
STATE_ROOT = STATE_ROOT.resolve()
AUDIT_DB = STATE_ROOT / 'trading_audit.sqlite3'
FINANCIAL_LEDGER = STATE_ROOT / 'financial_ledger.sqlite3'
DELIVERY_LEDGER = STATE_ROOT / 'delivery.json'
REPORT_ROOT = STATE_ROOT / 'reports'
RUNTIME_ROOT = STATE_ROOT / 'runtime'
LOG_ROOT = STATE_ROOT / 'logs'
CACHE_ROOT = STATE_ROOT / 'cache'
TMP_ROOT = RUNTIME_ROOT / 'tmp'
PAUSED = STATE_ROOT / 'PAUSED'
LEGACY_PAUSED = Path.home() / '.local/state/paper-report-delivery/PAUSED'


def state_root_for(code_root):
    """Explicit fixture roots stay isolated; default production readers use STATE_ROOT."""
    root = Path(code_root).resolve()
    return STATE_ROOT if root == CODE_ROOT else root


def maintenance_active(state_root=None):
    """Runtime flag stays distinct from the evidence archive on case-insensitive disks."""
    root=Path(state_root) if state_root is not None else STATE_ROOT
    if (root/'runtime/MAINTENANCE').exists():return True
    legacy=root/'MAINTENANCE';archive=root/'maintenance'
    if not legacy.exists():return False
    # Preserve old file markers and distinct legacy directory markers.
    if legacy.is_dir() and archive.is_dir() and os.path.samefile(legacy,archive):return False
    return True
