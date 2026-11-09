"""Bounded account PnL reads for an existing SDK owner; no financial transport."""
from datetime import datetime, timezone
import math
import threading
import time


class PnLFrameRejected(PermissionError):
    """An obsolete read can be replaced without resetting the SDK owner."""


class NativePnLCollector:
    def __init__(self, client, *, account, connection_generation, admitted,
                 allocate_request_id, publish, clock=time.time, monotonic=time.monotonic):
        if account != 'DUQ503649' or not isinstance(connection_generation,str) or not connection_generation:
            raise PermissionError('Exact Paper account and connection generation required')
        self.client, self.account = client, account
        self.connection_generation = connection_generation
        self.admitted, self.allocate_request_id, self.publish = admitted, allocate_request_id, publish
        self.clock, self.monotonic = clock, monotonic
        self.lock = threading.RLock()
        self.pending = None
        self.last_attempt = None
        self.closed = self.poisoned = False
        self.failure_reason = None

    def _cancel(self):
        pending, self.pending = self.pending, None
        if pending is not None and self.client.isConnected():
            try:
                self.client.cancelPnL(pending['request_id'])
            except Exception:
                self.poisoned = True

    def poll(self):
        with self.lock:
            if self.closed:
                return
            if self.poisoned:
                raise RuntimeError('Owned PnL subscription requires client reconciliation')
            elapsed = self.monotonic()
            if self.pending is not None:
                if elapsed - self.pending['elapsed_start'] >= 8:
                    self._cancel()
                    self.poisoned = True
                    raise RuntimeError('Owned PnL subscription timed out')
                return
            if self.last_attempt is not None and elapsed - self.last_attempt < 30:
                return
            admission=self.admitted()
            if not self.client.isConnected() or self.client.accounts != [self.account] or not admission:
                return
            request = self.allocate_request_id()
            if type(request) is not int or not 800000000 < request < 2147483648:
                raise RuntimeError('Invalid PnL request namespace')
            self.last_attempt = elapsed
            self.pending = dict(request_id=request, elapsed_start=elapsed,admission=admission,
                started_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat())
            try:
                self.client.reqPnL(request, self.account, '')
            except Exception:
                self._cancel()
                self.poisoned = True
                raise RuntimeError('PnL request outcome requires client reconciliation') from None

    def value(self, request, daily, unrealized, realized):
        with self.lock:
            pending = self.pending
            if self.closed or pending is None or request != pending['request_id']:
                return
            valid = (self.monotonic() - pending['elapsed_start'] < 8
                and self.client.isConnected() and self.client.accounts == [self.account] and bool(pending['admission']) and self.admitted()==pending['admission']
                and all(type(v) in (int, float) and abs(v) <= 1e100 and math.isfinite(v)
                        for v in (daily, unrealized, realized)))
            self._cancel()
            if not valid or self.poisoned:
                return
            receipt = dict(account=self.account, source='NATIVE_ACCOUNT_PNL',
                connection_generation=self.connection_generation, request_id=request,admission_generation=pending['admission'],
                started_at=pending['started_at'],
                observed_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                daily=daily, unrealized=unrealized, realized=realized,
                reset_policy='BROKER_CONFIGURED', basis='BROKER_ACCOUNT_AGGREGATE', grants_trading_permission=False)
            try:
                self.publish(receipt)
            except PnLFrameRejected:
                return
            except Exception:
                # Cancel already completed. Stop this actor rather than reconnect
                # a healthy SDK because a local evidence consumer failed.
                self.failure_reason = 'NATIVE_PNL_PUBLICATION_FAILED'
                self.closed = True

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self._cancel()
