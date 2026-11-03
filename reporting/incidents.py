"""Durable notification state; never owns trading permissions or broker state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time


class IncidentStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c, c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS incident_cursors (source TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incident_events (
                    event_id TEXT PRIMARY KEY, incident_key TEXT NOT NULL,
                    payload TEXT NOT NULL, resolved INTEGER NOT NULL, observed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_key TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                    state TEXT NOT NULL, opened REAL NOT NULL, resolved REAL);
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id INTEGER PRIMARY KEY, incident_key TEXT NOT NULL,
                    generation INTEGER NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL,
                    UNIQUE(incident_key, generation, kind));
                CREATE INDEX IF NOT EXISTS notification_pending ON notification_outbox(status,id);
                CREATE INDEX IF NOT EXISTS notification_incident_order ON notification_outbox(incident_key,id);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def ingest(self, event_id, incident_key, payload, *, resolved=False):
        if not event_id or not incident_key:
            raise ValueError('Explicit occurrence and incident identities required')
        encoded = json.dumps(payload, sort_keys=True)
        now = self.clock()
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            return self._ingest(c, event_id, incident_key, encoded, resolved, now)

    def _ingest(self, c, event_id, incident_key, encoded, resolved, now):
        """Caller owns transaction, including any source checkpoint."""
        old = c.execute('SELECT incident_key,payload,resolved FROM incident_events WHERE event_id=?', (event_id,)).fetchone()
        if old:
            if old != (incident_key, encoded, int(resolved)):
                raise ValueError('Occurrence identity reused with different evidence')
            return False
        row = c.execute('SELECT generation,state FROM incidents WHERE incident_key=?', (incident_key,)).fetchone()
        c.execute('INSERT INTO incident_events VALUES (?,?,?,?,?)', (event_id, incident_key, encoded, int(resolved), now))
        if resolved:
            if not row or row[1] != 'OPEN':
                return True
            generation = row[0]
            c.execute("UPDATE incidents SET state='RESOLVED',resolved=? WHERE incident_key=?", (now, incident_key))
            kind = 'RECOVERY'
        else:
            if row and row[1] == 'OPEN':
                generation = row[0]
                previous = c.execute('SELECT payload FROM notification_outbox WHERE incident_key=? AND generation=? ORDER BY id DESC LIMIT 1', (incident_key, generation)).fetchone()
                ranks = {'GREEN': 0, 'YELLOW': 1, 'RED': 2}
                severity = json.loads(encoded).get('severity')
                prior_severity = json.loads(previous[0]).get('severity') if previous else None
                protection = json.loads(encoded).get('protection_status')
                prior_protection = json.loads(previous[0]).get('protection_status') if previous else None
                if (protection in ('UNPROTECTED','PARTIALLY_PROTECTED','PROTECTION_UNKNOWN')
                        and protection != prior_protection):
                    kind = 'PROTECTION_' + protection
                elif ranks.get(severity, 0) > ranks.get(prior_severity, 0):
                    kind = 'ESCALATION_' + severity
                else:
                    return True
                if c.execute('SELECT 1 FROM notification_outbox WHERE incident_key=? AND generation=? AND kind=?', (incident_key, generation, kind)).fetchone():
                    return True
            else:
                generation = row[0] + 1 if row else 1
                c.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,NULL)', (incident_key, generation, 'OPEN', now))
                kind = 'ALERT'
        queued = json.loads(encoded)
        opened = c.execute('SELECT opened FROM incidents WHERE incident_key=?', (incident_key,)).fetchone()[0]
        queued.update(incident_opened_at=opened, queued_at=now)
        if resolved:
            queued.update(incident_resolved_at=now, duration_seconds=max(0, now - opened))
        c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,?,?,?,'PENDING')", (incident_key, generation, kind, json.dumps(queued, sort_keys=True)))
        return True

    def claim(self):
        """Reserve before transport; STARTED survives restart without replay."""
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT n.id,n.kind,n.payload,n.incident_key,n.generation FROM notification_outbox n
                WHERE n.status='PENDING' AND NOT EXISTS (
                    SELECT 1 FROM notification_outbox earlier
                    WHERE earlier.incident_key=n.incident_key AND earlier.id<n.id
                    AND earlier.status NOT IN ('SMTP_ACCEPTED','FEISHU_ACCEPTED')) ORDER BY n.id LIMIT 1""").fetchone()
            if row is None:
                return None
            c.execute("UPDATE notification_outbox SET status='STARTED' WHERE id=?", (row[0],))
            return dict(id=row[0], kind=row[1], payload=json.loads(row[2]), incident_key=row[3], generation=row[4])

    def finish(self, notification_id, status):
        if status not in ('SMTP_ACCEPTED', 'FEISHU_ACCEPTED', 'UNKNOWN'):
            raise ValueError('Outcome must retain delivery uncertainty')
        with closing(self.connect()) as c, c:
            result = c.execute("UPDATE notification_outbox SET status=? WHERE id=? AND status='STARTED'", (status, notification_id))
            if result.rowcount != 1:
                raise ValueError('Only a reserved notification can finish')

    def uncertain_notifications(self):
        with closing(self.connect()) as c:
            return bool(c.execute("SELECT 1 FROM notification_outbox WHERE status IN ('STARTED','UNKNOWN') LIMIT 1").fetchone())
