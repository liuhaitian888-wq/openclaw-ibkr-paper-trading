"""Process secretary queries on the existing Paper safety connection, never connect."""
from contextlib import closing
import copy
import json
import threading
from reporting.secretary_broker import initialize
from reporting.errors import redact
from trading.paper_safety_monitor import ACCOUNT

TAGS='AccountType,NetLiquidation,TotalCashValue,SettledCash,BuyingPower,AvailableFunds,ExcessLiquidity,$LEDGER:ALL'


class SecretaryBrokerOwner:
    def __init__(self,client,archive):
        self.client,self.archive=client,archive
        self.clock=client.monitor.clock
        self.lock=threading.RLock();self.pending=None;self.sequence=0;self.closed=False
        initialize(archive)
        # A new connection owner never repeats a previous owner's attempt.
        with closing(archive.connect()) as c,c:
            c.execute("UPDATE secretary_broker_queries SET state='UNKNOWN',finished=?,result=? WHERE state='STARTED'",
                      (self.clock(),json.dumps({'reason':'Broker owner changed; previous attempt retained, not replayed'})))

    def _finish(self,state,payload):
        p=self.pending
        if not p:return
        # Cancel only the subscription this query owns, including timeout/error paths.
        if p.get('summary_sent'):
            try:self.client.cancelAccountSummary(p['request_id'])
            except Exception:state='UNKNOWN';payload={'reason':'Owned account summary cancellation unverified'}
        encoded=json.dumps(redact(payload),ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>50000:
            state='UNAVAILABLE';encoded=json.dumps({'reason':'Broker result exceeds bounded response size'})
        with closing(self.archive.connect()) as c,c:
            c.execute("UPDATE secretary_broker_queries SET state=?,finished=?,result=? WHERE id=? AND state='STARTED'",
                      (state,self.clock(),encoded,p['id']))
        self.pending=None

    def summary(self,request_id,account,tag,value,currency):
        with self.lock:
            p=self.pending
            if not p or request_id!=p['request_id'] or not p.get('summary_sent'):return False
            if account=='All':
                # IBKR documents $LEDGER:ALL as all-managed-account aggregates.
                # Admit only cash ledger fields, with their native aggregate identity,
                # and only while exactly our one Paper account is managed.
                if self.client.accounts!=[ACCOUNT]:p['invalid']='SUMMARY_ACCOUNT_MISMATCH';return True
                if tag not in ('CashBalance','TotalCashBalance','ExchangeRate'):return True
            elif account!=ACCOUNT:p['invalid']='SUMMARY_ACCOUNT_MISMATCH';return True
            if (not all(isinstance(x,str) for x in (tag,value,currency)) or len(tag)>100 or len(value)>200 or len(currency)>8):
                p['invalid']='INVALID_SUMMARY_FIELD';return True
            if len(p['summary'])>=128 and (account,tag,currency) not in p['summary']:
                p['invalid']='SUMMARY_LIMIT';return True
            p['summary'][(account,tag,currency)]={'account':account,'tag':tag,'value':value,'currency':currency,'scope':'ALL_MANAGED_ACCOUNTS_SINGLE_ACCOUNT_VERIFIED' if account=='All' else 'EXACT_ACCOUNT'}
            return True

    def summary_end(self,request_id):
        with self.lock:
            if self.pending and request_id==self.pending['request_id']:
                self.pending['summary_end']=True;return True
            return False

    def error(self,request_id,code):
        with self.lock:
            if self.pending and request_id==self.pending['request_id']:
                self.pending['invalid']='BROKER_REQUEST_ERROR_'+str(code);return True
            return False

    def poll(self):
        """Returns True only when this poll started an owned reconciliation."""
        with self.lock:
            if self.closed:return False
            monitor=self.client.monitor;now=self.clock()
            if self.pending:
                p=self.pending
                if self.client.connection_generation!=p['generation'] or not self.client.isConnected():
                    self._finish('UNAVAILABLE',{'reason':'Broker connection changed'});return False
                if p['invalid'] or now-p['started']>=20:
                    self._finish('UNAVAILABLE',{'reason':p['invalid'] or 'Broker query timed out'});return False
                with monitor.lock:
                    s=monitor.state
                    ready=(monitor._complete() and s.get('reconciled_at',0)>=p['started']
                           and s.get('last_server_reply',0)>=p['started'])
                    if ready and p['summary_end']:
                        symbols=p['body']['symbols'];area=p['body']['area']
                        data={}
                        for name in ('positions','orders','executions','quotes'):
                            if area not in (name,'snapshot'):continue
                            values=s.get(name,{})
                            if symbols:
                                values={k:v for k,v in values.items() if (v.get('symbol',k) if isinstance(v,dict) else k) in symbols}
                            if len(values)>100:
                                data[name]={'truncated':True,'items':dict(list(values.items())[:100])}
                            else:data[name]=copy.deepcopy(values)
                        if area in ('account','cash','snapshot'):data['account_summary']=list(p['summary'].values())
                        if area=='quotes':
                            for symbol,q in data.get('quotes',{}).items():
                                if isinstance(q,dict):q['freshness']='FRESH' if q.get('data_type')==1 and all(type(q.get(k)) in (int,float) and 0<=now-q[k]<=5 for k in ('bid_at','ask_at')) else 'STALE_OR_UNENTITLED'
                            data['requested_unavailable_symbols']=[x for x in symbols if x not in data.get('quotes',{})]
                        payload=dict(account=ACCOUNT,environment='PAPER',source='OWNED_LIVE_BROKER_QUERY',
                            owner='ibkr-paper-safety.service',connection_generation=p['generation'],
                            requested_at=p['started'],observed_at=now,reconciled_at=s.get('reconciled_at'),
                            server_reply_at=s.get('last_server_reply'),data=data,
                            scope='Current native callbacks; execution history limited to broker session/API window; no cross-source atomicity',
                            grants_trading_permission=False)
                        if area in ('account','cash','snapshot') and not p['summary']:
                            self._finish('UNAVAILABLE',{'reason':'Empty account summary is not verified account data'})
                        else:self._finish('SUCCEEDED',payload)
                return False
            with closing(self.archive.connect()) as c:
                row=c.execute("SELECT id,request,queued FROM secretary_broker_queries WHERE state='READY' ORDER BY queued LIMIT 1").fetchone()
            if row is None:return False
            identity,raw,queued=row
            if not 0<=now-queued<=30:
                with closing(self.archive.connect()) as c,c:
                    c.execute("UPDATE secretary_broker_queries SET state='UNAVAILABLE',finished=?,result=? WHERE id=? AND state='READY'",
                        (now,json.dumps({'reason':'Query expired before broker admission'}),identity))
                return False
            with monitor.lock:
                if not self.client.isConnected() or self.client.accounts!=[ACCOUNT] or not monitor._complete():return False
            with closing(self.archive.connect()) as c,c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute("UPDATE secretary_broker_queries SET state='STARTED',started=? WHERE id=? AND state='READY'",(now,identity)).rowcount!=1:return False
            self.sequence+=1
            self.pending={'id':identity,'body':json.loads(raw),'started':now,'generation':self.client.connection_generation,
                'request_id':900000000+self.sequence,'summary':{},'summary_end':False,'summary_sent':False,'invalid':None}
            p=self.pending
            try:
                self.client.reconcile();self.client.reqCurrentTime()
                if p['body']['area'] in ('account','cash','snapshot'):
                    p['summary_sent']=True
                    self.client.reqAccountSummary(p['request_id'],'All',TAGS)
                else:p['summary_end']=True
            except Exception:
                self._finish('UNKNOWN',{'reason':'Broker request outcome uncertain; not replayed'})
            return True

    def close(self):
        with self.lock:
            self.closed=True
            if self.pending:self._finish('UNKNOWN',{'reason':'Broker owner closing; query not replayed'})
