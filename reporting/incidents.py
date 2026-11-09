"""Durable notification state; never owns trading permissions or broker state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time


def reminder_stage(elapsed):
    return (int(elapsed // 86400) + 2 if elapsed >= 86400 else
            2 if elapsed >= 7200 else 1 if elapsed >= 1800 else 0)


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
                CREATE TABLE IF NOT EXISTS notification_delivery (
                    notification_id INTEGER PRIMARY KEY,
                    attempt_started_at REAL NOT NULL, ack_received_at REAL,
                    status TEXT NOT NULL, provider_created_at REAL);
                CREATE TABLE IF NOT EXISTS notification_receipts (notification_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_preflight (
                    notification_id INTEGER PRIMARY KEY, first_at REAL NOT NULL,
                    attempts INTEGER NOT NULL, not_before REAL NOT NULL);
            ''')
        from .notification_reconciliation import initialize
        initialize(self)

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
            c.execute("UPDATE notification_outbox SET status='SUPERSEDED' WHERE incident_key=? "
                      "AND generation=? AND kind LIKE 'REMINDER_%' AND status='PENDING'", (incident_key,generation))
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
                    SELECT 1 FROM notification_preflight p WHERE p.notification_id=n.id AND p.not_before>?)
                AND NOT EXISTS (
                    SELECT 1 FROM json_each(n.payload,'$.recovery_members') member
                    JOIN notification_outbox source ON source.id=json_extract(member.value,'$.notification_id')
                    JOIN notification_outbox unresolved ON unresolved.incident_key=source.incident_key
                      AND unresolved.id<source.id
                    WHERE unresolved.status NOT IN ('SMTP_ACCEPTED','FEISHU_ACCEPTED','TELEGRAM_ACCEPTED','SUPERSEDED','NOT_SENT_EXHAUSTED','SUPPRESSED'))
                AND NOT EXISTS (
                    SELECT 1 FROM notification_outbox earlier
                    WHERE earlier.incident_key=n.incident_key AND earlier.id<n.id
                    AND earlier.status NOT IN ('SMTP_ACCEPTED','FEISHU_ACCEPTED','TELEGRAM_ACCEPTED','SUPERSEDED','NOT_SENT_EXHAUSTED','SUPPRESSED')) ORDER BY CASE WHEN json_extract(n.payload,'$.severity')='RED' THEN 0 WHEN n.kind!='SECRETARY_REPLY' AND n.kind NOT LIKE 'REPORT_%' THEN 1 WHEN json_extract(n.payload,'$.message_role') IN ('CONTROL','ACK','AUTH') THEN 2 ELSE 3 END,n.id LIMIT 1""", (self.clock(),)).fetchone()
            if row is None:
                return None
            c.execute("UPDATE notification_outbox SET status='STARTED' WHERE id=?", (row[0],))
            return dict(id=row[0], kind=row[1], payload=json.loads(row[2]), incident_key=row[3], generation=row[4])

    def finish(self, notification_id, status):
        if status not in ('SMTP_ACCEPTED', 'FEISHU_ACCEPTED', 'TELEGRAM_ACCEPTED', 'UNKNOWN'):
            raise ValueError('Outcome must retain delivery uncertainty')
        with closing(self.connect()) as c, c:
            result = c.execute("UPDATE notification_outbox SET status=? WHERE id=? AND status='STARTED'", (status, notification_id))
            if result.rowcount != 1:
                raise ValueError('Only a reserved notification can finish')

    def suppress(self, notification_id):
        """Explicit preference decision before wire, never a delivery receipt."""
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM notification_delivery WHERE notification_id=?',(notification_id,)).fetchone():
                raise ValueError('Cannot suppress an attempted delivery')
            if c.execute("UPDATE notification_outbox SET status='SUPPRESSED' WHERE id=? AND status='STARTED'",(notification_id,)).rowcount!=1:
                raise ValueError('Reserved unsent notification required')

    def uncertain_notifications(self):
        with closing(self.connect()) as c:
            return bool(c.execute("SELECT 1 FROM notification_outbox WHERE status IN ('STARTED','UNKNOWN') LIMIT 1").fetchone())

    def delivery_started(self, notification_id, at):
        with closing(self.connect()) as c, c:
            c.execute('INSERT INTO notification_delivery VALUES (?,?,NULL,?,NULL)',
                      (notification_id, at, 'STARTED'))

    def defer_unsent(self, notification_id):
        """Only a preflight before HTTP/operation reservation may return to pending."""
        now = self.clock()
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM notification_delivery WHERE notification_id=?',
                         (notification_id,)).fetchone():
                raise ValueError('Attempt may have been sent; reconciliation required')
            prior = c.execute('SELECT first_at,attempts FROM notification_preflight WHERE notification_id=?',
                              (notification_id,)).fetchone()
            first, attempts = (prior[0], prior[1] + 1) if prior else (now, 1)
            next_at = first + (15 if attempts == 1 else 45)
            c.execute('INSERT OR REPLACE INTO notification_preflight VALUES (?,?,?,?)',
                      (notification_id, first, attempts, next_at))
            status = 'NOT_SENT_EXHAUSTED' if attempts >= 3 else 'PENDING'
            changed = c.execute("UPDATE notification_outbox SET status=? WHERE id=? AND status='STARTED'",
                                (status, notification_id)).rowcount
            if changed != 1:
                raise ValueError('Reserved unsent notification required')
        return status

    def enqueue_current_summary(self, rollout):
        """One new snapshot per approved rollout, never a replay of historical notifications."""
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            # Establish elapsed-stage watermarks once when installing reminders.
            # Existing open history is represented by the one rollout summary, not N catch-up alerts.
            cursor='reminders:installation-baseline:v1'
            if not c.execute('SELECT 1 FROM incident_cursors WHERE source=?',(cursor,)).fetchone():
                baseline={k+':'+str(g):reminder_stage(self.clock()-opened)
                          for k,g,opened in c.execute("SELECT incident_key,generation,opened FROM incidents WHERE state='OPEN'")}
                c.execute('INSERT INTO incident_cursors VALUES (?,?)',(cursor,json.dumps(baseline)))
            key = 'monitoring-rollout:' + rollout
            if c.execute('SELECT 1 FROM notification_outbox WHERE incident_key=?', (key,)).fetchone():
                return False
            opened = c.execute("SELECT incident_key,opened FROM incidents WHERE state='OPEN'").fetchall()
            if not opened:
                return False
            payload = dict(severity='YELLOW', scope='CURRENT_UNRESOLVED_INCIDENTS', queued_at=self.clock(),
                           reason='当前尚未收到恢复证据的故障：\n' + '\n'.join(k for k,_ in opened[:40]),
                           action_taken='上线摘要；历史消息不重发。未恢复记录不代表最新券商状态，需看新鲜观测。',
                           grants_trading_permission=False)
            c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) "
                      "VALUES (?,1,'CURRENT_SUMMARY',?,'PENDING')", (key,json.dumps(payload,ensure_ascii=False)))
        return True

    def delivery_finished(self, notification_id, status, *, ack_at=None):
        with closing(self.connect()) as c, c:
            c.execute('UPDATE notification_delivery SET status=?,ack_received_at=? WHERE notification_id=?',
                      (status, ack_at, notification_id))

    def delivery_receipt(self, notification_id, receipt):
        encoded=json.dumps(receipt,sort_keys=True)
        with closing(self.connect()) as c,c:
            prior=c.execute('SELECT payload FROM notification_receipts WHERE notification_id=?',(notification_id,)).fetchone()
            if prior and prior[0]!=encoded:raise ValueError('Conflicting provider receipt')
            c.execute('INSERT OR IGNORE INTO notification_receipts VALUES (?,?)',(notification_id,encoded))

    def enqueue_due_reminders(self):
        """One latest elapsed stage per open occurrence; never replay uncertain sends."""
        now = self.clock()
        count = 0
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT payload FROM incident_cursors WHERE source=?',
                          ('reminders:installation-baseline:v1',)).fetchone()
            baseline=json.loads(row[0]) if row else {}
            for key, generation, opened in c.execute(
                    "SELECT incident_key,generation,opened FROM incidents WHERE state='OPEN'").fetchall():
                elapsed = now - opened
                stage = reminder_stage(elapsed)
                if not stage or stage <= baseline.get(key+':'+str(generation),0):
                    continue
                # An uncertain/pending earlier side effect cannot be bypassed by a new identity.
                if c.execute("SELECT 1 FROM notification_outbox WHERE incident_key=? AND generation=? "
                             "AND status NOT IN ('SMTP_ACCEPTED','FEISHU_ACCEPTED','TELEGRAM_ACCEPTED','SUPERSEDED','NOT_SENT_EXHAUSTED','SUPPRESSED') LIMIT 1",
                             (key, generation)).fetchone():
                    continue
                previous = c.execute('SELECT kind,payload FROM notification_outbox WHERE incident_key=? '
                                     'AND generation=? ORDER BY id DESC LIMIT 1', (key, generation)).fetchone()
                if not previous:
                    continue
                prior = json.loads(previous[1])
                # One-shot channel tests are not unresolved business incidents.
                # Preserve historical receipts, but never create recurring tests.
                if prior.get('scope') == 'NOTIFICATION_CHANNEL_TEST' or prior.get('test_only') is True:
                    continue
                if stage <= prior.get('reminder_stage', 0):
                    continue
                payload = {**prior, 'queued_at': now, 'reminder_stage': stage,
                           'duration_seconds': max(0, elapsed),
                           'scope': prior.get('scope', 'CURRENT_UNRESOLVED_INCIDENT'),
                           'action_taken': '持续故障提醒；仅代表故障尚未收到恢复证据，不代表最新券商状态'}
                c.execute("INSERT OR IGNORE INTO notification_outbox "
                          "(incident_key,generation,kind,payload,status) VALUES (?,?,?,?,'PENDING')",
                          (key, generation, 'REMINDER_' + str(stage), json.dumps(payload, sort_keys=True)))
                count += c.execute('SELECT changes()').fetchone()[0]
        return count
