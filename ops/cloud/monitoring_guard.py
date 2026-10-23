"""Approved diagnostic deployment identity and single owner, no trading gate."""
from contextlib import contextmanager
import json

from trading.production_guard import validate_workspace, instance_lock
from trading.production_diagnostics import context
from trading.production_paths import maintenance_active


@contextmanager
def monitoring_service(name, root):
    validate_workspace()
    manifest = json.loads((root / 'runtime/monitoring-deployment.json').read_text())
    actual = context()
    if (manifest.get('monitoring_approved') is not True or manifest.get('environment') != 'PAPER'
            or manifest.get('grants_trading_permission') is not False
            or not all(actual.get(key) and manifest.get(key) == actual[key]
                       for key in ('commit', 'branch', 'code_root', 'state_root'))
            or actual['state_root'] != str(root.resolve())):
        raise RuntimeError('Approved monitoring deployment identity required')
    if maintenance_active(root) and manifest.get('allow_during_maintenance') is not True:
        raise RuntimeError('Monitoring during maintenance is not approved')
    with instance_lock(root / 'runtime' / (name + '.lock')):
        print(json.dumps(dict(service=name, **actual), sort_keys=True))
        yield
