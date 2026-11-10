"""Existing monitor's local health journal; no broker or network operations."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from reporting.recovery import audit_write_probe
from .native_account_facts import account_facts, transport_facts, ACCOUNT


def disable_native_health_owner(coordinator):
    if coordinator.observations().get('NATIVE_BROKER_SESSION', {}).get('enabled') is True:
        coordinator.observe('NATIVE_BROKER_SESSION', 'DEGRADED', freshness='STALE', enabled=True,
            reason='Native base health owner disabled; old callback facts invalidated')
    coordinator.observe('NATIVE_BROKER_SESSION', 'PAUSED', freshness='UNKNOWN', enabled=False,
        reason='Native base health observation not configured', grants_trading_permission=False)


class NativeOwnerHealthBridge:
    def __init__(self, root, monitor, *, monotonic=time.monotonic):
        self.root = Path(root).resolve()
        self.monitor, self.coordinator = monitor, monitor.coordinator
        if (monitor.audit._path.parent.resolve() != self.root
                or self.coordinator.path.resolve() != self.root/'runtime/recovery.sqlite3'):
            raise PermissionError('Exact existing native owner and canonical journals required')
        self.monotonic = monotonic
        self.last_poll = self.last_probe = None
        self.closed = False
        self.last_error = None
        self._observe('NATIVE_BROKER_SESSION', 'DEGRADED', 'Waiting for exact native session proof', enabled=True)

    def _observe(self, module, state, reason, **evidence):
        freshness = 'FRESH' if state == 'HEALTHY' else 'STALE'
        try:
            if state != 'HEALTHY':
                old = self.coordinator.observations().get(module, {})
                if (old.get('state') == state and old.get('freshness') == freshness
                        and old.get('reason') == reason and old.get('producer') == 'NATIVE_CALLBACK_OWNER'
                        and all(old.get(k) == v for k, v in evidence.items())):
                    return True
            self.coordinator.observe(module, state, freshness=freshness, reason=reason,
                producer='NATIVE_CALLBACK_OWNER', grants_trading_permission=False, **evidence)
            return True
        except Exception as exc:
            # A local journal fault must not disconnect a healthy SDK. A stale
            # native leaf expires after ten seconds and actual write gates remain.
            self.last_error = type(exc).__name__
            return False

    def _probe_local_journals(self):
        try:
            audit_write_probe(self.monitor.audit._path)
        except Exception as exc:
            self._observe('DATABASE', 'FAILED', 'Native audit commit unavailable', error_type=type(exc).__name__)
            self._observe('AUDIT', 'FAILED', 'Native audit commit unavailable', error_type=type(exc).__name__)
        else:
            self._observe('DATABASE', 'HEALTHY', 'Native owner audit write committed')
            self._observe('AUDIT', 'HEALTHY', 'Native owner audit write committed')
        try:
            path = self.coordinator.path.resolve()
            payload = json.dumps(dict(module='LOCAL_STATE', event='NATIVE_OWNER_WRITE_PROBE',
                observed_at=datetime.fromtimestamp(self.monitor.clock(), timezone.utc).isoformat()))
            with closing(sqlite3.connect(path.as_uri()+'?mode=rw', uri=True, timeout=.2)) as c, c:
                rowid = c.execute('INSERT INTO module_events(payload) VALUES (?)', (payload,)).lastrowid
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as c:
                if c.execute('SELECT payload FROM module_events WHERE id=?', (rowid,)).fetchone() != (payload,):
                    raise RuntimeError('Local journal write readback differs')
        except Exception as exc:
            self._observe('LOCAL_STATE', 'FAILED', 'Native local journal readback unavailable', error_type=type(exc).__name__)
        else:
            self._observe('LOCAL_STATE', 'HEALTHY', 'Native local journal committed and independently read back')

    def invalidate(self, reason):
        self._observe('NATIVE_BROKER_SESSION', 'DEGRADED', reason, enabled=True)

    def poll(self):
        if self.closed:
            return
        elapsed = self.monotonic()
        if self.last_poll is not None and elapsed-self.last_poll < 1:
            return
        self.last_poll = elapsed
        if self.last_probe is None or elapsed-self.last_probe >= 60:
            self.last_probe = elapsed
            self._probe_local_journals()
        with self.monitor.lock:
            now = self.monitor.clock()
            try:
                target = self.root/'runtime/currency-book.latest.json'
                if target.is_symlink() or target.parent.is_symlink():
                    raise PermissionError('Owned native cashbook path required')
                with target.open('rb') as stream:
                    content = stream.read(100001)
                if len(content) > 100000:
                    raise ValueError('Native cashbook exceeds bounded evidence size')
                book = json.loads(content)
                session = transport_facts(book, self.monitor.state, now=now)
            except Exception as exc:
                self.invalidate('Native session evidence unavailable: '+type(exc).__name__)
                return
            if not self._observe('NATIVE_BROKER_SESSION', 'HEALTHY', 'Exact native account-ready callback and server clock',
                    enabled=True, account=ACCOUNT, environment='PAPER',
                    connection_generation=session['connection_generation'], broker_epoch=session['broker_epoch'],
                    ledger_request_id=session['ledger_request_id'], ledger_observed_at=session['ledger_observed_at']):
                return
            if not self._observe('IBKR_CONNECTION', 'HEALTHY', 'Existing authenticated native SDK owner',
                    account=ACCOUNT, environment='PAPER', connection_generation=session['connection_generation']):return
            try:
                if self.monitor.cashbook_publication_state.get('blocked'):
                    raise PermissionError('Native ledger persistence recovery required')
                facts = account_facts(book, self.monitor.state, now=now,
                    pnl_publication_blocked=self.monitor.pnl_publication_state.get('blocked', False))
            except Exception as exc:
                self._observe('ACCOUNT', 'DEGRADED', 'Native account evidence unavailable: '+type(exc).__name__)
                return
            if not self._observe('ACCOUNT', 'HEALTHY', 'Complete typed native account facts; no financial permission',
                    account=ACCOUNT, environment='PAPER', native_account_facts=facts):return
            try:unknown = self.coordinator.uncertainties(kind='order')
            except Exception as exc:
                for module in ('ORDERS','EXECUTIONS'):
                    self._observe(module,'DEGRADED','Broker operation journal unavailable',error_type=type(exc).__name__)
                return
            if unknown:
                for module in ('ORDERS', 'EXECUTIONS'):
                    self._observe(module, 'DEGRADED', 'Uncertain broker operation retained; no automatic replay',
                        uncertain_operations=unknown)
                return
            for module, key in (('ORDERS', 'orders'), ('EXECUTIONS', 'executions')):
                rows = self.monitor.state[key].values()
                valid = all(row.get('account') == ACCOUNT for row in rows)
                self._observe(module, 'HEALTHY' if valid else 'DEGRADED', 'Complete exact-account native '+key,
                    account=ACCOUNT, environment='PAPER', broker_epoch=facts['broker_epoch'],
                    count=len(self.monitor.state[key]), reconciled_at=self.monitor.state['reconciled_at'])
            self._observe('POSITIONS', 'HEALTHY', 'Complete native position callbacks; ownership is separate',
                account=ACCOUNT, environment='PAPER', broker_epoch=facts['broker_epoch'],
                count=len(self.monitor.state['positions']), reconciled_at=self.monitor.state['reconciled_at'])

    def close(self):
        if not self.closed:
            self.closed = True
            self._observe('NATIVE_BROKER_SESSION', 'PAUSED', 'Native owner stopped; fresh callback proof required', enabled=True)
