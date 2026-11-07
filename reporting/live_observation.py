"""Bounded, dedicated, read-only IBKR observation; owns every subscription/thread."""
import hashlib
import math
import threading
import time
import os
from datetime import datetime, timezone
from .errors import redact

class PaperIdentityError(ValueError):
    pass


TAGS={'NetLiquidation':'net_liquidation','TotalCashValue':'total_cash_value','AvailableFunds':'available_funds','BuyingPower':'buying_power'}


def probe(host='127.0.0.1',port=7497,client_id=18765,timeout=15,*,symbols=(),expected_account=None):
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.execution import ExecutionFilter
    class Observer(EWrapper,EClient):
        def __init__(self):
            EClient.__init__(self,self);self.ready=threading.Event();self.ends=set();self.accounts=[];self.values={};self.errors=[]
            self.positions=[];self.orders=[];self.executions=[];self.quotes={};self.pnl_value=None;self.server_time=None
        def nextValidId(self,orderId):self.ready.set()
        def managedAccounts(self,accountsList):self.accounts=[a for a in accountsList.split(',') if a]
        def currentTime(self,t):self.server_time=t
        def error(self,reqId,*args):self.errors.append(redact({'request_id':reqId,'raw_callback_arguments':list(args)}))
        def accountSummary(self,reqId,account,tag,value,currency):
            if self.accounts!=[account] or tag not in TAGS:return
            try:v=float(value)
            except ValueError:v=None
            if v is not None and (not math.isfinite(v) or abs(v)>1e100):v=None
            self.values[TAGS[tag]]={'value':v,'currency':currency or None,'source':'IBKR accountSummary',
                'source_timestamp':datetime.now(timezone.utc).isoformat(),'freshness':'FRESH' if v is not None else 'UNKNOWN'}
        def accountSummaryEnd(self,reqId):self.ends.add('summary')
        def position(self,a,c,p,cost):self.positions.append({'account':a,'conId':c.conId,'symbol':c.symbol,'currency':c.currency,'position':str(p),'avgCost':cost})
        def positionEnd(self):self.ends.add('positions')
        def openOrder(self,i,c,o,s):self.orders.append({'account':o.account,'perm_id':o.permId,'order_id':i,'order_ref':o.orderRef,'client_id':o.clientId,'symbol':c.symbol,'conId':c.conId,'side':o.action,'quantity':str(o.totalQuantity),'status':s.status,
            'parent_id':o.parentId,'order_type':o.orderType,'limit_price':o.lmtPrice,
            'aux_price':o.auxPrice,'tif':o.tif})
        def openOrderEnd(self):self.ends.add('orders')
        def execDetails(self,r,c,e):self.executions.append({'account':e.acctNumber,'exec_id':e.execId,'perm_id':e.permId,'order_id':e.orderId,'symbol':c.symbol,'side':e.side,'shares':str(e.shares),'time':e.time,'price':e.price,'order_ref':e.orderRef,'currency':c.currency,'sec_type':c.secType,'con_id':c.conId})
        def execDetailsEnd(self,r):self.ends.add('executions')
        def pnl(self,r,d,u,real):self.pnl_value={'daily':d,'unrealized':u,'realized':real}
        def marketDataType(self,r,t):self.quotes.setdefault(r,{})['data_type']=t
        def tickPrice(self,r,t,p,a):
            if t in (1,2) and p>0:self.quotes.setdefault(r,{})[{1:'bid',2:'ask'}[t]]=p;self.quotes[r]['received_at']=datetime.now(timezone.utc).isoformat()
    c=Observer();thread=None;subscriptions=[];requested=False;result=None
    try:
        c.connect(host,port,clientId=client_id);thread=threading.Thread(target=c.run,name='ibkr-maintenance-observer',daemon=True);thread.start()
        if not c.ready.wait(timeout/2):raise TimeoutError('IBKR handshake timeout')
        end=time.monotonic()+timeout/2
        while not c.accounts and time.monotonic()<end:time.sleep(.05)
        if len(c.accounts)!=1 or not c.accounts[0].startswith('DU'):raise PaperIdentityError('Exactly one Paper account required')
        if expected_account and c.accounts!=[expected_account]:raise PaperIdentityError('Account identity mismatch')
        c.reqCurrentTime();c.reqAccountSummary(8165,'All',','.join(TAGS));c.reqPositions();c.reqAllOpenOrders();c.reqExecutions(8166,ExecutionFilter());c.reqPnL(8167,c.accounts[0],'');requested=True
        for i,symbol in enumerate(symbols,8200):
            contract=Contract();contract.symbol=symbol;contract.secType='STK';contract.exchange='SMART';contract.currency='USD'
            c.reqMktData(i,contract,'',False,False,[]);subscriptions.append(i)
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            complete={'summary','positions','orders','executions'}<=c.ends and c.server_time and c.pnl_value is not None
            quotes=all('bid' in c.quotes.get(i,{}) and 'ask' in c.quotes.get(i,{}) for i in subscriptions)
            if complete and quotes:break
            time.sleep(.05)
        result={'observed_at':datetime.now(timezone.utc).isoformat(),'source':'REAL_IBKR','account_id':c.accounts[0],
            'account_fingerprint':hashlib.sha256(c.accounts[0].encode()).hexdigest(),'environment':'PAPER',
            'complete':{'summary','positions','orders','executions'}<=c.ends and len(c.values)==len(TAGS),
            'account':c.values,'positions':c.positions,'orders':c.orders,'executions':c.executions,'pnl':c.pnl_value,
            'resource_during':{'fd':len(os.listdir('/dev/fd')),'threads':threading.active_count(),'subscriptions':len(subscriptions)},
            'server_time':c.server_time,'end_markers':sorted(c.ends),'quotes':{s:c.quotes.get(i,{}) for i,s in enumerate(symbols,8200)},'raw_errors':c.errors}
    finally:
        try:
            if c.isConnected():
                for i in subscriptions:c.cancelMktData(i)
                if requested:c.cancelAccountSummary(8165);c.cancelPositions();c.cancelPnL(8167)
        finally:
            reader=getattr(c,'reader',None)
            c.disconnect()
            if thread:thread.join(timeout=5)
            if reader:reader.join(timeout=5)
        if reader and reader.is_alive():raise RuntimeError('IBKR reader did not stop')
        if thread and thread.is_alive():raise RuntimeError('IBKR observer worker failed to stop; no replacement allowed')
    result['resources']={'worker_stopped':True,'subscriptions_cancelled':len(subscriptions),'connected_after_close':c.isConnected(),'fd_after':len(os.listdir('/dev/fd')),'threads_after':threading.active_count(),'reader_stopped':not reader or not reader.is_alive()}
    return result
