"""Opt-in background evidence collector; queues only, never sends or trades."""
import os
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector
from trading.production_paths import RUNTIME_ROOT, REPORT_ROOT, STATE_ROOT
from ops.cloud.monitoring_guard import monitoring_service


def main():
    os.umask(0o077)
    if not (RUNTIME_ROOT / 'INCIDENT_COLLECTION_ARMED').is_file():
        print('INCIDENT_COLLECTION_NOT_ARMED')
        return
    config = Path.home() / '.config/openclaw/paper-observer.json'
    if config.stat().st_mode & 0o077:
        raise PermissionError('Observer configuration must be mode 0600')
    expected = json.loads(config.read_text())['expected_account']
    with monitoring_service('incident-collector', STATE_ROOT):
        collector = IncidentCollector(IncidentStore(RUNTIME_ROOT / 'recovery.sqlite3'))
        return collect_once(collector, REPORT_ROOT, RUNTIME_ROOT, expected)


def collect_once(collector, reports, runtime, expected):
    jobs = {
        'modules': collector.module_events,
        'unknown': collector.unknown_operations,
        'rejections': lambda: collector.rejections(reports / 'order_rejections/history.jsonl'),
        'protection': lambda: collector.protection_reports(reports / 'position_protection/history.jsonl', expected),
        'guard': lambda: collector.protection_reports(reports / 'position_guard/history.jsonl', expected, guard=True),
        'runtime': lambda: collector.runtime_snapshots(runtime / 'cloud-status.json', runtime / 'paper-observer.latest.json', expected),
    }
    counts = {}
    errors = {}
    for name, run in jobs.items():
        try:
            counts[name] = run()
        except Exception as exc:
            errors[name] = type(exc).__name__  # Never output raw records or private values.
    print(json.dumps(dict(collected=counts, errors=errors, grants_trading_permission=False), sort_keys=True))
    return 2 if errors else 0



if __name__ == '__main__':
    raise SystemExit(main())
