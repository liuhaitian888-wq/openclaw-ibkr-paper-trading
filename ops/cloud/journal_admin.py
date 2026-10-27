"""Explicit journal evidence reconciliation; no broker, mail or SQLite writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.journal_backup import inspect_backup, restore_journal
from reporting.journal_recovery import inspect_rotation, recover_rotation
from trading.production_paths import STATE_ROOT, maintenance_active

JOURNALS = ('order_rejections', 'position_protection', 'position_guard')


def contained(path, parent):
    path = Path(path).absolute(); parent = Path(parent).absolute()
    if parent.is_symlink(): raise ValueError('Approved parent must not be a symlink')
    try: relative = path.relative_to(parent)
    except ValueError: raise ValueError('Path must stay within the approved state directory')
    if '..' in relative.parts or path == parent:
        raise ValueError('A distinct contained path is required')
    current = parent
    for part in relative.parts:
        current = current/part
        if current.is_symlink(): raise ValueError('Symlink component refused')
    if not path.resolve().is_relative_to(parent.resolve()):
        raise ValueError('Path escapes the approved directory')
    return path


def dispatch(action, root, *, journal=None, backup=None, target=None, token=None):
    root = Path(root)
    if action in ('inspect', 'recover'):
        if journal not in JOURNALS: raise ValueError('Use a declared business journal')
        path = contained(root/'reports'/journal/'history.jsonl', root)
        if action == 'inspect': return inspect_rotation(path)
        if not (root/'PAUSED').is_file() or not maintenance_active(root):
            raise PermissionError('Explicit rotation recovery requires PAUSED and MAINTENANCE')
        if any((root/'runtime'/name).exists() for name in ('EMAIL_ALERTS_ARMED', 'INCIDENT_COLLECTION_ARMED')):
            raise PermissionError('Keep production collection and sending disarmed during reconciliation')
        return recover_rotation(path, token or '')
    if action not in ('inspect-backup', 'restore') or backup is None:
        raise ValueError('Specify an evidence bundle')
    backup = contained(backup, root)
    if action == 'inspect-backup': return inspect_backup(backup)
    if target is None: raise ValueError('Specify a new isolated restore directory')
    target = contained(target, root/'monitoring-tests')
    return restore_journal(backup, target, token or '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'recover', 'inspect-backup', 'restore'))
    parser.add_argument('--journal', choices=JOURNALS)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--token')
    args = parser.parse_args()
    from trading.production_guard import validate_workspace
    validate_workspace()
    result = dispatch(args.action, STATE_ROOT, journal=args.journal, backup=args.backup,
                      target=args.target, token=args.token)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__': main()
