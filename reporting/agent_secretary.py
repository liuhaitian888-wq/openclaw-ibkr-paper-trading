"""Auditable secretary records. No broker transport or private model reasoning."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time


class SecretaryArchive:
    """Each method owns its connection; occurrence IDs come from the caller."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c, c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS secretary_events(
                    occurrence TEXT PRIMARY KEY, conversation TEXT NOT NULL,
                    origin TEXT NOT NULL, kind TEXT NOT NULL, parent TEXT,
                    payload TEXT NOT NULL, recorded_at REAL NOT NULL,
                    FOREIGN KEY(parent) REFERENCES secretary_events(occurrence));
                CREATE INDEX IF NOT EXISTS secretary_conversation
                    ON secretary_events(conversation,recorded_at);
                CREATE TABLE IF NOT EXISTS secretary_runs(
                    occurrence TEXT PRIMARY KEY, instruction TEXT NOT NULL,
                    model TEXT NOT NULL, state TEXT NOT NULL,
                    result_event TEXT, started_at REAL NOT NULL,
                    FOREIGN KEY(instruction) REFERENCES secretary_events(occurrence),
                    FOREIGN KEY(result_event) REFERENCES secretary_events(occurrence));
            ''')

    def connect(self):
        c = sqlite3.connect(self.path, timeout=2)
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def append(self, occurrence, conversation, *, origin, kind, payload, parent=None):
        if origin not in ('USER', 'MODEL', 'TOOL', 'SYSTEM'):
            raise ValueError('Explicit provenance required')
        if not all(isinstance(v, str) and v for v in (occurrence, conversation, kind)):
            raise ValueError('Occurrence, conversation and kind required')
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if parent:
                row = c.execute('SELECT conversation FROM secretary_events WHERE occurrence=?', (parent,)).fetchone()
                if row is None or row[0] != conversation:
                    raise ValueError('Parent must belong to this conversation')
            values = (conversation, origin, kind, parent, encoded)
            prior = c.execute('SELECT conversation,origin,kind,parent,payload FROM secretary_events WHERE occurrence=?', (occurrence,)).fetchone()
            if prior:
                if prior != values:
                    raise ValueError('Occurrence identity reused with different content')
                return False
            c.execute('INSERT INTO secretary_events VALUES(?,?,?,?,?,?,?)',
                      (occurrence, *values, self.clock()))
            return True

    def reserve_run(self, occurrence, *, instruction, model):
        """Commit before paid execution. Existing STARTED/UNKNOWN is never replayed."""
        if not occurrence or not model:
            raise ValueError('Run occurrence and explicit model required')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT origin FROM secretary_events WHERE occurrence=?', (instruction,)).fetchone()
            if row is None or row[0] != 'USER':
                raise ValueError('Run must reference a user instruction')
            prior = c.execute('SELECT instruction,model FROM secretary_runs WHERE occurrence=?', (occurrence,)).fetchone()
            if prior:
                if prior != (instruction, model):
                    raise ValueError('Run occurrence conflict')
                return False
            c.execute('INSERT INTO secretary_runs VALUES(?,?,?,\'STARTED\',NULL,?)',
                      (occurrence, instruction, model, self.clock()))
            return True

    def finish_run(self, occurrence, *, state, result_event=None):
        if state not in ('SUCCEEDED', 'FAILED', 'UNKNOWN'):
            raise ValueError('Explicit outcome required')
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT instruction,state,result_event FROM secretary_runs WHERE occurrence=?', (occurrence,)).fetchone()
            if row is None:
                raise ValueError('Unreserved run')
            if row[1] != 'STARTED':
                if (row[1], row[2]) == (state, result_event):
                    return False
                raise ValueError('Terminal outcome cannot be overwritten')
            if state == 'SUCCEEDED':
                result = c.execute('SELECT parent,origin FROM secretary_events WHERE occurrence=?', (result_event,)).fetchone()
                if result is None or result[0] != row[0] or result[1] not in ('MODEL', 'TOOL'):
                    raise ValueError('Result must reference its user instruction')
            c.execute('UPDATE secretary_runs SET state=?,result_event=? WHERE occurrence=?',
                      (state, result_event, occurrence))
            return True

    def history(self, conversation, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Bounded history required')
        with closing(self.connect()) as c:
            rows = c.execute('SELECT occurrence,origin,kind,parent,payload,recorded_at FROM secretary_events WHERE conversation=? ORDER BY rowid DESC LIMIT ?', (conversation, limit)).fetchall()
        return [dict(occurrence=i, origin=o, kind=k, parent=p, payload=json.loads(v), recorded_at=t)
                for i, o, k, p, v, t in reversed(rows)]
