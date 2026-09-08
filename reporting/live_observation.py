"""Isolated read-only IBKR reporting observation; never changes Trading state."""
import hashlib
import math
import threading
import time
from datetime import datetime, timezone
from .errors import redact

TAGS = {'NetLiquidation':'net_liquidation','TotalCashValue':'total_cash_value',
        'AvailableFunds':'available_funds','BuyingPower':'buying_power'}

def probe(host='127.0.0.1', port=7497, client_id=18765, timeout=15):
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    class Observer(EWrapper,EClient):
        def __init__(self):
            EClient.__init__(self,self)
            self.ready=threading.Event();self.done=threading.Event()
            self.accounts=[];self.values={};self.errors=[]
        def nextValidId(self,orderId):self.ready.set()
        def managedAccounts(self,accountsList):self.accounts=accountsList.strip(',').split(',')
        def error(self,reqId,*args):
            self.errors.append(redact({'request_id':reqId,'raw_callback_arguments':list(args)}))
        def accountSummary(self,reqId,account,tag,value,currency):
            if len(self.accounts)!=1 or account!=self.accounts[0] or tag not in TAGS:return
            try:v=float(value)
            except ValueError:v=None
            if v is not None and (not math.isfinite(v) or abs(v)>1e100):v=None
            self.values[TAGS[tag]]={'value':v,'currency':currency or None,
                'source':'IBKR accountSummary','source_timestamp':datetime.now(timezone.utc).isoformat(),
                'freshness':'FRESH' if v is not None else 'MISSING'}
        def accountSummaryEnd(self,reqId):self.done.set()
    c=Observer();thread=None
    try:
        c.connect(host,port,clientId=client_id)
        thread=threading.Thread(target=c.run,daemon=True);thread.start()
        if not c.ready.wait(timeout/2):raise TimeoutError('IBKR handshake timeout')
        deadline=time.monotonic()+timeout/2
        while not c.accounts and time.monotonic()<deadline:time.sleep(.05)
        if len(c.accounts)!=1 or not c.accounts[0].startswith('DU'):raise ValueError('Exactly one Paper account required')
        c.reqAccountSummary(8165,'All',','.join(TAGS))
        c.done.wait(timeout)
        return {'observed_at':datetime.now(timezone.utc).isoformat(),'source':'REAL_IBKR',
                'account_id':c.accounts[0],'account_fingerprint':hashlib.sha256(c.accounts[0].encode()).hexdigest(),
                'complete':c.done.is_set() and len(c.values)==len(TAGS),
                'account':c.values,'raw_errors':c.errors}
    finally:
        if c.isConnected():
            c.cancelAccountSummary(8165);c.disconnect()
        if thread:thread.join(timeout=1)
