"""One bounded native cash subscription on an existing read-only SDK owner."""
from datetime import datetime,timezone
from decimal import Decimal
import json
import threading
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from .currency_book import cashbook,normalized_tag
from .settlement_book import settlement_book

ACCOUNT='DUQ503649'
KEEP={'CashBalance','ExchangeRate','AvailableFunds','TotalCashValue','NetLiquidation',
      'AccountReady','AccountType','SettledCashByDate','SettledCashByDate-S'}

class NativeCashCollector:
    def __init__(self,client,*,account,connection_generation,admitted,publish,observe,
                 clock=time.time,monotonic=time.monotonic):
        if account!=ACCOUNT or not isinstance(connection_generation,str) or not connection_generation:
            raise PermissionError('Exact Paper account and connection generation required')
        self.client,self.account=client,account
        self.connection_generation=connection_generation
        self.admitted,self.publish,self.observe=admitted,publish,observe
        self.clock,self.monotonic=clock,monotonic
        self.lock=threading.RLock();self.pending=None;self.closed=False;self.poisoned=False
        self.sequence=0;self.last_attempt=None

    def _stamp(self):return datetime.fromtimestamp(self.clock(),timezone.utc).isoformat()

    def _cancel(self,request):
        if not self.client.isConnected():return
        self.client.cancelAccountUpdatesMulti(request)

    def _finish(self,reason,*,poison=False):
        """Always close just the owned subscription, including malformed snapshots."""
        pending=self.pending;self.pending=None
        if pending:
            try:self._cancel(pending['id'])
            except Exception:
                poison=True;reason='CASHBOOK_CANCEL_FAILED'
        self.poisoned=self.poisoned or poison
        if reason:self.observe('DEGRADED',reason,enabled=True,grants_trading_permission=False)

    def poll(self):
        with self.lock:
            if self.closed:return
            if self.poisoned:raise RuntimeError('Cash subscription requires owned-client reconnect')
            elapsed=self.monotonic()
            if self.pending:
                if elapsed-self.pending['elapsed_start']>=8:
                    self._finish('CASHBOOK_REQUEST_TIMEOUT',poison=True)
                    raise RuntimeError('Cash subscription timed out; reconnect before another request')
                return
            if self.last_attempt is not None and elapsed-self.last_attempt<5:return
            if not self.client.isConnected() or self.client.accounts!=[self.account] or not self.admitted():return
            started=self._stamp()
            self.sequence+=1
            if self.sequence>=1000000:raise RuntimeError('Cash request namespace exhausted; reconnect required')
            request=800000000+self.sequence
            self.pending={'id':request,'started_at':started,'elapsed_start':elapsed,'values':{},'invalid':None,'bytes':0}
            self.last_attempt=elapsed
            try:self.client.reqAccountUpdatesMulti(request,self.account,'',False)
            except Exception:
                self._finish('CASHBOOK_REQUEST_SEND_FAILED',poison=True)
                raise RuntimeError('Cash request outcome requires owned-client reconnect')

    def value(self,request,account,model,key,value,currency):
        with self.lock:
            p=self.pending
            if self.closed or not p or request!=p['id']:return
            if account!=self.account or model!='':p['invalid']='CASHBOOK_ACCOUNT_OR_MODEL_MISMATCH';return
            if not isinstance(key,str) or len(key)>100:p['invalid']='CASHBOOK_FIELD_INVALID';return
            if normalized_tag(key) not in KEEP:return
            if (not isinstance(value,str) or len(value)>5000 or not isinstance(currency,str) or len(currency)>4):
                p['invalid']='CASHBOOK_FIELD_INVALID';return
            identity=(key,currency)
            row=dict(key=key,value=value,currency=currency,account=account,model=model)
            if identity in p['values']:
                if p['values'][identity]!=row:p['invalid']='CASHBOOK_CONFLICTING_VALUES'
                return
            size=len(json.dumps(row,ensure_ascii=False).encode())
            if len(p['values'])>=128 or p['bytes']+size>90000:p['invalid']='CASHBOOK_SNAPSHOT_TOO_LARGE';return
            p['values'][identity]=row;p['bytes']+=size

    def end(self,request):
        with self.lock:
            p=self.pending
            if self.closed or not p or request!=p['id']:return
            if self.monotonic()-p['elapsed_start']>=8:
                self._finish('CASHBOOK_REQUEST_TIMEOUT',poison=True);return
            if p['invalid']:
                self._finish(p['invalid']);return
            try:
                if self.client.accounts!=[self.account] or not self.client.isConnected() or not self.admitted():
                    raise PermissionError('Native admission changed during cash read')
                receipt=dict(account=self.account,source='NATIVE_ACCOUNT_UPDATE_MULTI',request_id=request,
                    started_at=p['started_at'],finished_at=self._stamp(),complete=True,
                    connection_generation=self.connection_generation,values=list(p['values'].values()))
                values=[SimpleNamespace(account=r['account'],tag=r['key'],value=r['value'],currency=r['currency']) for r in receipt['values']]
                book=cashbook(values,self.account)
                base=book['base_currency']
                if base not in book['currencies'] or 'USD' not in book['currencies']:raise PermissionError('Explicit USD and base cash required')
                for row in book['currencies'].values():
                    if abs(Decimal(row['amount']))>Decimal('1e100'):raise ValueError('Unavailable native cash amount')
                    row['source']='IBKR accountUpdateMulti/$LEDGER'
                settlement_book(receipt,account=self.account,base_currency=base,
                    as_of_day=datetime.fromtimestamp(self.clock(),ZoneInfo('America/New_York')).date().isoformat())
                book.update(observed_at=receipt['finished_at'],cash_read_started_at=receipt['started_at'],
                    cash_read_finished_at=receipt['finished_at'],settlement_receipt=receipt,
                    connection_generation=self.connection_generation,requested_currencies=['USD']+([] if base=='USD' else [base]),
                    currency_coverage='USD_AND_BASE_VERIFIED',
                    ledger_evidence=[dict(source='NATIVE_ACCOUNT_UPDATE_MULTI',request_id=request,started_at=receipt['started_at'],ended_at=receipt['finished_at'])])
                if len(json.dumps(book,ensure_ascii=False).encode())>100000:raise ValueError('Bounded complete cashbook required')
            except Exception:
                self._finish('CASHBOOK_NATIVE_EVIDENCE_INVALID');return
            self._finish(None)
            if self.poisoned:return
            try:self.publish(book)
            except Exception:
                self.observe('DEGRADED','CASHBOOK_PUBLICATION_FAILED',enabled=True,grants_trading_permission=False);return
            self.observe('HEALTHY','Complete native cash and settlement facts; no spending permission',
                enabled=True,connection_generation=self.connection_generation,request_id=request,grants_trading_permission=False)

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True;self._finish('CASHBOOK_OWNER_CLOSED')
