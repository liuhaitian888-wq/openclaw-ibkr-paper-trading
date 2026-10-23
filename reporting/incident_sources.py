"""Bounded background ingestion of existing evidence; no broker or mail calls."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json

from .health import MODULE_DEPENDENCIES


class EvidenceChanged(RuntimeError):
    """Source changed discontinuously; reconcile rather than replay history."""


class IncidentCollector:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _cursor(c, source):
        row = c.execute('SELECT payload FROM incident_cursors WHERE source=?', (source,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _save(c, source, value):
        c.execute('INSERT OR REPLACE INTO incident_cursors VALUES (?,?)', (source, json.dumps(value, sort_keys=True)))

    def _event(self, c, identity, key, payload, resolved=False):
        self.store._ingest(c, identity, key, json.dumps(payload, sort_keys=True), resolved, self.store.clock())

    def rejections(self, path, limit=100):
        """First scan baselines EOF; changed/truncated logs require explicit review."""
        if not 1 <= limit <= 100:
            raise ValueError('Batch limit must be 1..100')
        source = 'rejections:' + str(path.resolve())
        with closing(self.store.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            cursor = self._cursor(c, source)
            try:
                handle = path.open('rb')
            except FileNotFoundError:
                if cursor and cursor['inode'] is not None:
                    raise EvidenceChanged('Rejection source disappeared; checkpoint retained')
                self._save(c, source, dict(inode=None, offset=0, anchor=''))
                return 0
            with handle:
                import os
                stat = os.fstat(handle.fileno())
                inode = [stat.st_dev, stat.st_ino]
                if cursor is None:
                    offset = stat.st_size
                    handle.seek(max(0, offset - 64))
                    self._save(c, source, dict(inode=inode, offset=offset, anchor=hashlib.sha256(handle.read(offset - handle.tell())).hexdigest()))
                    return 0
                offset = cursor['offset']
                if cursor['inode'] is not None:
                    if inode != cursor['inode'] or stat.st_size < offset:
                        raise EvidenceChanged('Rejection log rotated/truncated; checkpoint retained')
                    handle.seek(max(0, offset - 64))
                    anchor = hashlib.sha256(handle.read(offset - handle.tell())).hexdigest()
                    if anchor != cursor['anchor']:
                        raise EvidenceChanged('Rejection log rewritten; checkpoint retained')
                handle.seek(offset)
                count = 0
                for _ in range(limit):
                    start = handle.tell()
                    raw = handle.readline(65537)
                    if len(raw) > 65536:
                        raise ValueError('Rejection record exceeds bounded size')
                    if not raw or not raw.endswith(b'\n'):
                        break  # Partial writes are retried from their start.
                    payload = json.loads(raw)
                    plan = payload.get('local_plan_id')
                    if not isinstance(plan, str) or not plan or not payload.get('timestamp'):
                        raise ValueError('Rejection lacks occurrence evidence/order identity')
                    evidence = dict(payload, severity='YELLOW', scope='ORDER',
                                    recovery_condition='Explicit order reconciliation required',
                                    grants_trading_permission=False)
                    self._event(c, f'{source}:{inode}:{start}', 'rejection:' + plan, evidence)
                    offset = handle.tell()
                    count += 1
                handle.seek(max(0, offset - 64))
                anchor = hashlib.sha256(handle.read(offset - handle.tell())).hexdigest()
                self._save(c, source, dict(inode=inode, offset=offset, anchor=anchor))
                return count

    def module_events(self, limit=100):
        """Consume coordinator events from the same recovery DB atomically."""
        if not 1 <= limit <= 100:
            raise ValueError('Batch limit must be 1..100')
        source = 'recovery:module_events'
        with closing(self.store.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_events'").fetchone():
                self._save(c, source, 0)
                return 0
            maximum = c.execute('SELECT COALESCE(MAX(id),0) FROM module_events').fetchone()[0]
            cursor = self._cursor(c, source)
            if cursor is None:
                self._save(c, source, maximum)
                return 0
            if maximum < cursor:
                raise EvidenceChanged('Recovery event sequence regressed')
            rows = c.execute('SELECT id,payload FROM module_events WHERE id>? ORDER BY id LIMIT ?', (cursor, limit)).fetchall()
            for identity, raw in rows:
                event = json.loads(raw)
                module = event['module']
                if module not in MODULE_DEPENDENCIES:
                    raise ValueError('Unknown health registry module')
                state = event['state']
                resolved = state == 'HEALTHY' and event.get('freshness') == 'FRESH'
                if resolved:
                    observed = datetime.fromisoformat(event['observed_at']).astimezone(timezone.utc).timestamp()
                    resolved = 0 <= self.store.clock() - observed <= 120
                if resolved or state in ('FAILED', 'OFFLINE', 'DEGRADED'):
                    # Diagnostic scope only: this collector never applies a pause.
                    payload = dict(event, severity='GREEN' if resolved else 'YELLOW',
                                   scope='MODULE', grants_trading_permission=False,
                                   action_taken='notification_recorded_only')
                    self._event(c, f'{source}:{identity}', 'module:' + module, payload, resolved)
                cursor = identity
            self._save(c, source, cursor)
            return len(rows)

    def unknown_operations(self):
        """Observe new UNKNOWN order outcomes; never replay or resolve orders."""
        source = 'recovery:order_operations'
        with closing(self.store.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_attempts'").fetchone():
                self._save(c, source, {})
                return 0
            rows = c.execute("SELECT identity,status FROM operation_attempts WHERE kind='order' ORDER BY identity LIMIT 1001").fetchall()
            if len(rows) > 1000:
                raise EvidenceChanged('Order operation baseline exceeds bounded collector capacity')
            prior = self._cursor(c, source)
            current = dict(rows)
            if prior is None:
                self._save(c, source, current)
                return 0
            if not prior.keys() <= current.keys():
                raise EvidenceChanged('Order operation evidence disappeared')
            count = 0
            for identity, state in rows:
                if state == 'UNKNOWN' and prior.get(identity) != state:
                    payload = dict(operation_identity=identity, severity='RED', scope='ACCOUNT',
                                   reason='Broker order outcome UNKNOWN',
                                   action_taken='notification_recorded_only_no_replay',
                                   recovery_condition='Explicit broker reconciliation and existing risk gates',
                                   grants_trading_permission=False)
                    self._event(c, source + ':' + identity + ':UNKNOWN', 'unknown-order:' + identity, payload)
                    count += 1
            self._save(c, source, current)
            return count
