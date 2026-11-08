"""Bounded owner-authorized Paper protective stops. No entry or cancel methods."""
import asyncio
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from trading.protection_repair import ACCOUNT,repair_once
from trading.production_diagnostics import context
from ops.cloud.monitoring_guard import monitoring_service


class Broker:
    """One request lifecycle owner; at most one non-overlapping L1 stream/run."""
    def __init__(self):
        from ib_async import IB
        self.ib=IB();self.subscription=None;self.quote_times={};self.errors=[]
        self.ib.errorEvent+=self.error
        self.ib.pendingTickersEvent+=self.prices
    def clock(self):return time.time()
    def error(self,req,code,message,*args):self.errors.append({'order_id':req,'code':code})
    def prices(self,tickers):
        for ticker in tickers:
            if self.subscription and ticker.contract.conId==self.subscription.conId:
                for tick in ticker.ticks:
                    if tick.tickType in (1,2):self.quote_times['bid_at' if tick.tickType==1 else 'ask_at']=self.clock()
    async def connect(self):
        from ib_async import StartupFetchNONE
        await self.ib.connectAsync('127.0.0.1',4002,clientId=18992,readonly=True,fetchFields=StartupFetchNONE,timeout=8)
        if self.ib.managedAccounts()!=[ACCOUNT]:raise PermissionError('Exact Paper session required')
    def close(self):
        try:
            if self.subscription and self.ib.isConnected():self.ib.cancelMktData(self.subscription)
        finally:self.ib.disconnect()
    async def bounded(self,future):return await asyncio.wait_for(future,8)
    async def snapshot(self):
        from ib_async import ExecutionFilter
        if not self.ib.isConnected() or self.ib.managedAccounts()!=[ACCOUNT]:raise PermissionError('Exact connected Paper identity required')
        positions=await self.bounded(self.ib.reqPositionsAsync())
        oldest=self.clock()
        opens=await self.bounded(self.ib.reqAllOpenOrdersAsync())
        await self.bounded(self.ib.reqCompletedOrdersAsync(apiOnly=False))
        await self.bounded(self.ib.reqExecutionsAsync(ExecutionFilter(acctCode=ACCOUNT)))
        if any(p.account!=ACCOUNT for p in positions) or any(t.order.account!=ACCOUNT for t in opens):raise PermissionError('Mixed-account readback')
        return {'account':ACCOUNT,'complete':True,'ends':['positions','orders','completed_orders','executions'],
            'observed_at':self.clock(),'oldest_end_at':oldest,
            'positions':[{'account':p.account,'symbol':p.contract.symbol,'quantity':str(p.position),'con_id':p.contract.conId,'sec_type':p.contract.secType,'currency':p.contract.currency} for p in positions],
            'orders':[{'account':t.order.account,'symbol':t.contract.symbol,'con_id':t.contract.conId,'side':t.order.action,'order_type':t.order.orderType,'quantity':str(t.order.totalQuantity),'remaining':str(t.orderStatus.remaining),'status':t.orderStatus.status,'order_ref':t.order.orderRef,'perm_id':t.order.permId,'aux_price':t.order.auxPrice,'tif':t.order.tif,'transmit':t.order.transmit,'currency':t.contract.currency,'sec_type':t.contract.secType} for t in opens]}
    def contract(self,p):
        from ib_async import Contract
        return Contract(conId=p['con_id'],symbol=p['symbol'],secType='STK',currency='USD',exchange='SMART')
    async def details(self,p):
        rows=await self.bounded(self.ib.reqContractDetailsAsync(self.contract(p)))
        if len(rows)!=1 or rows[0].contract.conId!=p['con_id'] or rows[0].contract.currency!='USD' or rows[0].contract.secType!='STK':
            raise PermissionError('Unique exact broker contract details required')
        d=rows[0]
        return {'min_tick':d.minTick,'timezone':d.timeZoneId,'trading_hours':d.liquidHours}
    async def quote(self,p):
        if self.subscription:raise PermissionError('Only one owned quote stream per bounded run')
        self.subscription=self.contract(p);self.ib.reqMarketDataType(1)
        ticker=self.ib.reqMktData(self.subscription,'',False,False)
        deadline=self.clock()+15
        while self.clock()<deadline:
            if set(self.quote_times)=={'bid_at','ask_at'} and ticker.marketDataType==1:
                return {'bid':ticker.bid,'ask':ticker.ask,'data_type':ticker.marketDataType,**self.quote_times}
            await asyncio.sleep(.1)
        raise TimeoutError('No fresh real-time protective reference; no order reserved')
    async def submit_stop(self,p):
        from ib_async import StopOrder
        # This is the only side-effect call in this adapter. No cancel method.
        order=StopOrder('SELL',p['quantity'],float(p['stop_price']),tif='GTC',outsideRth=False,
                        account=ACCOUNT,orderRef=p['order_ref'],transmit=True)
        trade=self.ib.placeOrder(self.contract(p),order)
        deadline=self.clock()+8
        while self.clock()<deadline:
            if trade.orderStatus.status in ('Submitted','PreSubmitted','Inactive'):break
            await asyncio.sleep(.1)
        native=await self.snapshot()
        matching=[o for o in native['orders'] if o['order_ref']==p['order_ref']]
        positions=[x for x in native['positions'] if x['con_id']==p['con_id']]
        from decimal import Decimal
        covered=(len(matching)==1 and matching[0]['account']==ACCOUNT and matching[0]['con_id']==p['con_id']
            and matching[0]['side']=='SELL' and matching[0]['order_type']=='STP' and matching[0]['tif']=='GTC'
            and matching[0]['transmit'] is True and matching[0]['perm_id']>0
            and matching[0]['status'] in ('Submitted','PreSubmitted')
            and Decimal(matching[0]['remaining'])==p['quantity'] and Decimal(matching[0]['quantity'])==p['quantity']
            and Decimal(str(matching[0]['aux_price']))==Decimal(p['stop_price'])
            and len(positions)==1 and Decimal(positions[0]['quantity'])==p['quantity']
            and not any(o['symbol']==p['symbol'] and o['order_ref']!=p['order_ref'] and o['status'] not in ('Filled','Cancelled','ApiCancelled','Inactive') for o in native['orders'])
            and 0<=self.clock()-native['oldest_end_at']<=5)
        rejected=(trade.orderStatus.status=='Inactive' and not matching and any(e['order_id']==trade.order.orderId and e['code']==201 for e in self.errors))
        return {'status':'CONFIRMED' if covered else 'REJECTED' if rejected else 'UNKNOWN',
                'order_id':trade.order.orderId,'perm_id':trade.order.permId,'native_status':trade.orderStatus.status,
                'post_submit_readback_at':native['observed_at'],'matching_orders':matching,'positions':positions,
                'errors':self.errors,'ownership':'NEW_SCOPED_PROTECTIVE_INTENT_ONLY'}


def publish(root,result):
    path=root/'runtime/protection-repair.latest.json';temporary=path.with_suffix('.tmp')
    with temporary.open('w') as f:json.dump(result,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
    temporary.chmod(0o600);temporary.replace(path)
    from reporting.recovery import RecoveryCoordinator
    store=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
    store.observe('PROTECTION_REPAIR','PAUSED' if result['state'].startswith('WAIT') else 'DEGRADED',freshness='STALE',
                  reason=result['state'],enabled=True,grants_entry_permission=False)
    if result['state'] in ('CONFIRMED','REJECTED','RECONCILIATION_REQUIRED') and result.get('order_ref'):
        from reporting.incidents import IncidentStore
        from contextlib import closing
        outbox=IncidentStore(root/'runtime/recovery.sqlite3')
        p=result.get('plan',{});text='旧仓补保护｜'+str(result.get('symbol'))+'｜'+result['state']+'\n数量：'+str(p.get('quantity'))+'；止损触发价：'+str(p.get('stop_price'))+' USD。\n'+('原生回执与独立回读已核验。' if result['state']=='CONFIRMED' else '尚未确认保护完成；不自动重放，请先对账。')+'\nPFE旧单与交易暂停不变；普通STP仅常规时段触发，跳空时成交价可能低于触发价。'
        with closing(outbox.connect()) as c,c:
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('protection-repair:'+result['order_ref'],json.dumps({'reason':text,'delivery_transport':'telegram','message_role':'CONTROL'},ensure_ascii=False)))


async def run(root):
    scope=json.loads((root/'runtime/legacy-protection-scope.json').read_text())
    from trading.protection_repair import regular_session,validate_scope
    validate_scope(scope,context(),root,now=time.time())
    if not regular_session(time.time()):return {'state':'WAIT_SESSION','orders_sent':0}
    broker=Broker()
    try:
        await broker.connect()
        return await repair_once(scope,context(),root,broker,now=time.time())
    finally:broker.close()


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    with monitoring_service('legacy-protection-repair',root):
        try:result=asyncio.run(asyncio.wait_for(run(root),110))
        except Exception as exc:
            result={'state':'BLOCKED','reason':type(exc).__name__,'orders_sent':'UNKNOWN_CHECK_LEDGER'}
            # Cancellation/timeout may have happened inside transport. Preserve
            # and report the exact durable identity rather than hiding UNKNOWN.
            try:
                from trading.protection_repair import Journal
                attempts=Journal(root/'trading_audit.sqlite3','legacy-protection-20261109-v1').attempts()
                uncertain=[(ref,v) for ref,v in attempts.items() if v['status'] in ('STARTED','UNKNOWN')]
                if uncertain:
                    ref,value=uncertain[0];result.update(state='RECONCILIATION_REQUIRED',order_ref=ref,plan=value['plan'],symbol=value['plan']['symbol'])
            except Exception:pass
        result.update(observed_at=datetime.now(timezone.utc).isoformat(),grants_entry_permission=False)
        publish(root,result);print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
