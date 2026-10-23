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
                return True
            generation = row[0] + 1 if row else 1
            c.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,NULL)', (incident_key, generation, 'OPEN', now))
            kind = 'ALERT'
        c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,?,?,?,'PENDING')", (incident_key, generation, kind, encoded))
        return True

    def claim(self):
        """Reserve before transport; STARTED survives restart without replay."""
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT n.id,n.kind,n.payload FROM notification_outbox n
                WHERE n.status='PENDING' AND NOT EXISTS (
                    SELECT 1 FROM notification_outbox earlier
                    WHERE earlier.incident_key=n.incident_key AND earlier.id<n.id
                    AND earlier.status!='SMTP_ACCEPTED') ORDER BY n.id LIMIT 1""").fetchone()
            if row is None:
                return None
            c.execute("UPDATE notification_outbox SET status='STARTED' WHERE id=?", (row[0],))
            return dict(id=row[0], kind=row[1], payload=json.loads(row[2]))

    def finish(self, notification_id, status):
        if status not in ('SMTP_ACCEPTED', 'UNKNOWN'):
            raise ValueError('Outcome must retain SMTP uncertainty')
        with closing(self.connect()) as c, c:
            result = c.execute("UPDATE notification_outbox SET status=? WHERE id=? AND status='STARTED'", (status, notification_id))
            if result.rowcount != 1:
                raise ValueError('Only a reserved notification can finish')
