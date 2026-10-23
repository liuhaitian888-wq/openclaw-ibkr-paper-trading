"""Opt-in background evidence collector; queues only, never sends or trades."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector
from trading.production_paths import RUNTIME_ROOT, REPORT_ROOT


def main():
    os.umask(0o077)
    if not (RUNTIME_ROOT / 'INCIDENT_COLLECTION_ARMED').is_file():
        print('INCIDENT_COLLECTION_NOT_ARMED')
        return
    collector = IncidentCollector(IncidentStore(RUNTIME_ROOT / 'recovery.sqlite3'))
    modules = collector.module_events()
    unknown = collector.unknown_operations()
    rejections = collector.rejections(REPORT_ROOT / 'order_rejections/history.jsonl')
    print(f'INCIDENT_EVIDENCE_COLLECTED modules={modules} rejections={rejections} unknown={unknown}; no permission change')


if __name__ == '__main__':
    main()
