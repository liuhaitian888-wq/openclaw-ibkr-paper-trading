"""One-shot read-only qualification actor on a caller-owned SDK connection.

No connect, worker, financial call or automatic retry. Native marketRule callbacks
have no request occurrence ID: a qualifier is single-use and its connection owner
must not multiplex another request for the same rule on this connection.
"""
import copy
import threading
import time
from datetime import datetime,timezone
from .native_price_rules import ladder,number

ACCOUNT='DUQ503649'


class NativeContractQualifier:
    def __init__(self,client,*,generation,admitted,allocate_request_id,clock=time.time,monotonic=time.monotonic):
        if not isinstance(generation,str) or not 1<=len(generation)<=200:raise ValueError('Owned generation required')
        self.client,self.generation=client,generation
        self.admitted,self.allocate,self.clock,self.monotonic=admitted,allocate_request_id,clock,monotonic
        self.lock=threading.RLock();self.phase='IDLE';self.failure=None;self._result=None
        self.rows=[];self.request_id=None;self.rule_id=None;self.started=None;self.contract_pending=False;self.cancel_failure=None

    def _stamp(self):return datetime.fromtimestamp(self.clock(),timezone.utc).isoformat()

    def _current(self):
        evidence=self.admitted()
        return (isinstance(evidence,dict) and evidence.get('account')==ACCOUNT
            and evidence.get('environment')=='PAPER'
            and evidence.get('connection_generation')==self.generation
            and self.client.isConnected() is True)

    def _cancel_contract(self):
        if not self.contract_pending:return
        self.contract_pending=False
        try:
            from ibapi.server_versions import MIN_SERVER_VER_CANCEL_CONTRACT_DATA
            version=self.client.serverVersion() if hasattr(self.client,'serverVersion') else None
            if self._current() and type(version) is int and version>=MIN_SERVER_VER_CANCEL_CONTRACT_DATA:
                self.client.cancelContractData(self.request_id)
        except Exception as exc:self.cancel_failure=type(exc).__name__

    def _fail(self,reason):
        self._cancel_contract()
        self.phase='FAILED';self.failure=reason;self._result=None;self.rows=[]

    def start(self,contract):
        with self.lock:
            if self.phase!='IDLE':raise PermissionError('Qualification occurrence is single-use; never retry it')
            self.phase='CONTRACT';self.started=self.monotonic()
            try:
                if not self._current():raise PermissionError('Exact current owned Paper connection required')
                self.symbol=contract.symbol;self.exchange=contract.exchange
                if (contract.secType!='STK' or contract.currency!='USD'
                        or not isinstance(self.symbol,str) or not 1<=len(self.symbol)<=32
                        or self.exchange!='SMART'):
                    raise PermissionError('Explicit SMART USD stock qualification required')
                self.request_id=self.allocate()
                if type(self.request_id) is not int or not 0<self.request_id<=2147483647:
                    raise ValueError('Unique positive bounded request ID required')
                self.contract_pending=True
                self.client.reqContractDetails(self.request_id,contract)
            except Exception as exc:self._fail('CONTRACT_REQUEST_'+type(exc).__name__)

    def poll(self):
        with self.lock:
            if self.phase not in ('CONTRACT','RULE','COMPLETE'):return
            try:
                if not self._current():self._fail('OWNER_CHANGED')
                elif self.phase!='COMPLETE' and self.monotonic()-self.started>=8:self._fail('QUALIFICATION_TIMEOUT')
            except Exception as exc:self._fail('OWNER_CHECK_'+type(exc).__name__)

    def contract_details(self,request_id,details):
        with self.lock:
            if self.phase!='CONTRACT' or request_id!=self.request_id:return False
            try:
                if not self._current() or self.monotonic()-self.started>=8:raise PermissionError('Late or foreign connection')
                c=details.contract
                if (c.symbol!=self.symbol or c.secType!='STK' or c.currency!='USD'
                        or type(c.conId) is not int or not 0<c.conId<=2147483647
                        or not isinstance(c.primaryExchange,str) or not 1<=len(c.primaryExchange)<=80
                        or number(details.minTick)<=0):raise ValueError('Exact stock identity required')
                if self.rows:raise ValueError('Ambiguous contract details')
                exchanges=details.validExchanges.split(',');ids=details.marketRuleIds.split(',')
                if (len(exchanges)!=len(ids) or len(exchanges)>256 or exchanges.count(self.exchange)!=1):
                    raise ValueError('Unambiguous native exchange rule mapping required')
                rule=ids[exchanges.index(self.exchange)]
                if not 1<=len(rule)<=10 or not rule.isascii() or not rule.isdecimal() or not 0<int(rule)<=2147483647:
                    raise ValueError('Positive native rule ID required')
                self.rule_id=int(rule)
                self.rows.append(dict(source='NATIVE_CONTRACT_DETAILS',complete=False,connection_generation=self.generation,
                    request_id=self.request_id,symbol=self.symbol,sec_type='STK',currency='USD',con_id=c.conId,
                    primary_exchange=c.primaryExchange,min_tick=str(number(details.minTick)),
                    valid_exchanges=details.validExchanges,market_rule_ids=details.marketRuleIds,observed_at=self._stamp()))
            except Exception as exc:self._fail('CONTRACT_DETAILS_'+type(exc).__name__)
            return True

    def contract_end(self,request_id):
        with self.lock:
            if self.phase!='CONTRACT' or request_id!=self.request_id:return False
            self.contract_pending=False
            try:
                if len(self.rows)!=1 or not self._current() or self.monotonic()-self.started>=8:
                    raise PermissionError('Exact complete timely contract required')
                self.rows[0]['complete']=True
                self.phase='RULE'
                self.client.reqMarketRule(self.rule_id)
            except Exception as exc:self._fail('MARKET_RULE_REQUEST_'+type(exc).__name__)
            return True

    def market_rule(self,rule_id,increments):
        with self.lock:
            if self.phase!='RULE' or rule_id!=self.rule_id:return False
            try:
                if not self._current() or self.monotonic()-self.started>=8:raise PermissionError('Late or foreign connection')
                if not isinstance(increments,(list,tuple)) or not 1<=len(increments)<=256:
                    raise ValueError('Bounded native ladder required')
                rows=[dict(low_edge=str(number(x.lowEdge)),increment=str(number(x.increment))) for x in increments]
                ladder(rows)
                rule=dict(source='NATIVE_MARKET_RULE',complete=True,connection_generation=self.generation,
                    market_rule_id=rule_id,observed_at=self._stamp(),increments=rows)
                self._result=dict(contract=self.rows[0],rule=rule,grants_trading_permission=False)
                self.phase='COMPLETE'
            except Exception as exc:self._fail('MARKET_RULE_'+type(exc).__name__)
            return True

    def result(self):
        with self.lock:
            self.poll()
            return copy.deepcopy(self._result) if self.phase=='COMPLETE' else None

    def close(self):
        # Cancel only an owned outstanding contract read when server>=215 supports
        # it. marketRule has no cancel; ignore late finite callbacks, never disconnect a peer.
        with self.lock:
            self._cancel_contract()
            self.phase='CLOSED';self._result=None;self.rows=[]
