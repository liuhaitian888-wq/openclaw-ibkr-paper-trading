"""Read-only scanner requests owned by the existing Paper safety connection."""
from contextlib import closing
import json
import threading
import time
import uuid

from reporting.broad_screening import initialize

CODES = ('MOST_ACTIVE', 'TOP_PERC_GAIN', 'TOP_PERC_LOSE')


def queue(archive, code='MOST_ACTIVE', *, now=None, identity=None):
    now = time.time() if now is None else now
    if code not in CODES:
        raise ValueError('扫描代码：MOST_ACTIVE / TOP_PERC_GAIN / TOP_PERC_LOSE')
    initialize(archive)
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE broker_screen_requests SET state='EXPIRED',finished=? WHERE state='QUEUED' AND expires<?", (now, now))
        prior = c.execute("SELECT id,state FROM broker_screen_requests WHERE code=? AND (state IN ('QUEUED','STARTED') OR state IN ('SUCCEEDED','FAILED','UNKNOWN') AND finished>?) ORDER BY queued DESC LIMIT 1", (code, now-60)).fetchone()
        if prior:
            return dict(id=prior[0], state=prior[1], reused=True)
        count = c.execute('SELECT count(*) FROM broker_screen_requests WHERE queued>?', (now-3600,)).fetchone()[0]
        if count >= 12:
            raise ValueError('每小时最多12次只读scanner；不增加额度以绕过限制')
        key = identity or 'scanner:'+str(uuid.uuid4())
        c.execute("INSERT OR IGNORE INTO broker_screen_requests VALUES(?,?,'QUEUED',?,?,NULL,NULL,NULL,?)",
                  (key, code, now, now+180, json.dumps({'scope': 'PAPER_EXISTING_OWNER_ONLY', 'grants_trading_permission': False})))
        return dict(id=key, state=c.execute('SELECT state FROM broker_screen_requests WHERE id=?', (key,)).fetchone()[0], reused=False)


class BrokerScanner:
    def __init__(self, client, archive, *, clock=time.time):
        self.client, self.archive, self.clock = client, archive, clock
        self.active = None
        self.lock = threading.RLock()
        self.next_id = 80000
        initialize(archive)
        with closing(archive.connect()) as c, c:
            c.execute("UPDATE broker_screen_requests SET state='UNKNOWN',finished=?,payload=? WHERE state='STARTED'",
                      (clock(), json.dumps({'reason': 'Previous connection ended before durable result; never auto-replay'})))

    def data(self, request, rank, details):
        with self.lock:
            if self.active is None or request != self.active['request'] or not isinstance(rank, int) or not 0 <= rank < 50:
                return
            contract = getattr(details, 'contract', None) or getattr(details, 'summary', None)
            if contract is None:
                return
            con_id=getattr(contract,'conId',0)
            if not isinstance(con_id,int) or con_id<=0:return
            self.active['rows'][rank] = dict(symbol=str(getattr(contract, 'symbol', ''))[:32],
                con_id=con_id, exchange=str(getattr(contract, 'primaryExchange', ''))[:32],
                currency=str(getattr(contract, 'currency', ''))[:12], sec_type=str(getattr(contract, 'secType', ''))[:12])

    def end(self, request):
        with self.lock:
            if self.active is not None and self.active['request'] == request:
                self.active['done'] = True

    def error(self, request, code):
        with self.lock:
            if self.active is not None and self.active['request'] == request:
                self.active['error'] = code
                return True
        return False

    def _finish(self, status, reason):
        active = self.active
        if active is None:
            return
        # Only this adapter's request is cancelled, never broker orders/quotes.
        try:
            self.client.cancelScannerSubscription(active['request'])
        except Exception:
            status, reason = 'UNKNOWN', 'Scanner cancellation outcome unverified; no replay'
        with closing(self.archive.connect()) as c, c:
            if status == 'SUCCEEDED':
                for rank, row in active['rows'].items():
                    if row['symbol'] and row['con_id'] > 0 and row['currency'] == 'USD' and row['sec_type'] == 'STK':
                        c.execute('INSERT OR IGNORE INTO broker_screen_results VALUES(?,?,?,?,?,?,?,?)',
                                  (active['key'], rank, row['symbol'], row['con_id'], row['exchange'], row['currency'], row['sec_type'], self.clock()))
            c.execute("UPDATE broker_screen_requests SET state=?,finished=?,payload=? WHERE id=? AND state='STARTED'",
                      (status, self.clock(), json.dumps({'reason': reason, 'received_rows': len(active['rows']),
                       'actual_scanner_request': True, 'quotes_included': False, 'grants_trading_permission': False}), active['key']))
        self.active = None
        from reporting.incidents import IncidentStore
        from reporting.recovery import RecoveryCoordinator
        root=self.archive.path.parent
        RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('BROKER_SCANNER','HEALTHY' if status=='SUCCEEDED' else 'DEGRADED',
            freshness='FRESH',reason=reason,enabled=True,ranked_candidates=len(active['rows']),grants_trading_permission=False)
        if not active['key'].startswith('schedule:'):
            store=IncidentStore(root/'runtime/recovery.sqlite3')
            text='IBKR Paper只读扫描：'+status+'\n'+reason+'\n'+', '.join(row['symbol'] for _,row in sorted(active['rows'].items())[:15])+'\n真实候选排名，不包含报价，不改变实时权限或交易门禁。'
            with closing(store.connect()) as c,c:
                c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,'PENDING')",
                    ('broker-scanner:'+active['key'],json.dumps({'reason':text,'message_role':'CONTROL','delivery_transport':'telegram'},ensure_ascii=False)))

    def poll(self, *, admitted):
        now = self.clock()
        with self.lock:
            if self.active:
                a = self.active
                if a.get('error') is not None:
                    self._finish('FAILED', 'IBKR_SCANNER_ERROR_'+str(a['error']))
                elif a.get('done'):
                    self._finish('SUCCEEDED', 'Native scannerDataEnd received; ranked candidates only')
                elif now-a['started'] >= 20 or not admitted:
                    self._finish('UNKNOWN', 'Scanner timeout or dependency lost; not replayed')
                return
            with closing(self.archive.connect()) as c, c:
                c.execute('BEGIN IMMEDIATE')
                c.execute("UPDATE broker_screen_requests SET state='EXPIRED',finished=? WHERE state='QUEUED' AND expires<?", (now, now))
                if not admitted:
                    return
                row = c.execute("SELECT id,code FROM broker_screen_requests WHERE state='QUEUED' AND expires>=? ORDER BY queued LIMIT 1", (now,)).fetchone()
                if not row:
                    return
                c.execute("UPDATE broker_screen_requests SET state='STARTED',started=?,connection=? WHERE id=? AND state='QUEUED'",
                          (now, self.client.connection_generation, row[0]))
            request = self.next_id
            self.next_id += 1
            self.active = dict(key=row[0], request=request, started=now, rows={}, done=False, error=None)
            from ibapi.scanner import ScannerSubscription
            subscription = ScannerSubscription()
            subscription.instrument = 'STK'
            subscription.locationCode = 'STK.US.MAJOR'
            subscription.scanCode = row[1]
            subscription.numberOfRows = 50
            try:
                self.client.reqScannerSubscription(request, subscription, [], [])
            except Exception:
                self._finish('UNKNOWN', 'Read request dispatch outcome unverified')

    def close(self):
        with self.lock:
            self._finish('UNKNOWN', 'Existing connection closing before result; no replay')
