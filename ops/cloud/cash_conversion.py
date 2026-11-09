"""One finite own-cash EUR/USD conversion; stock trading remains paused."""
import asyncio,json,os,sys,time
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.protection_repair import Broker as ReadbackBroker
from ops.cloud.monitoring_guard import monitoring_service
from trading.cash_conversion import ACCOUNT,SCOPE,validate,plan,reserve,finish,reconcile
from trading.currency_book import fetch_paper_cashbook
from trading.production_diagnostics import context
from reporting.recovery import RecoveryCoordinator


def publish_legacy_cashbook(root,book):
 """Keep known FX outcome independent of a latest-file publication failure."""
 path=root/'runtime/monitoring-deployment.json'
 if path.exists():
  try:
   if path.is_symlink() or path.stat().st_size>100000:return 'SKIPPED_OWNER_UNVERIFIED'
   owner=json.loads(path.read_text()).get('native_cashbook_observation_approved')
   if owner is True:return 'CONTINUOUS_OWNER_CONFIGURED'
   if owner is not None and owner is not False:return 'SKIPPED_OWNER_UNVERIFIED'
  except (ValueError,OSError):return 'SKIPPED_OWNER_UNVERIFIED'
 try:
  temp=root/'runtime/currency-book.latest.fx.tmp'
  with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(book,f);f.flush();os.fsync(f.fileno())
  temp.chmod(0o600);temp.replace(root/'runtime/currency-book.latest.json')
  return 'LEGACY_BOOK_PUBLISHED'
 except (OSError,ValueError,TypeError):return 'PUBLICATION_FAILED_NATIVE_RECEIPT_RETAINED'


class Broker(ReadbackBroker):
 async def connect(self):
  from ib_async import StartupFetchNONE
  await self.ib.connectAsync('127.0.0.1',4002,clientId=18995,readonly=True,fetchFields=StartupFetchNONE,timeout=8)
  if self.ib.managedAccounts()!=[ACCOUNT]:raise PermissionError('Exact Paper identity required')
 async def reference(self):
  from ib_async import Forex
  rows=await self.bounded(self.ib.qualifyContractsAsync(Forex('EURUSD')))
  if len(rows)!=1 or (rows[0].conId,rows[0].symbol,rows[0].currency,rows[0].secType)!=(12087792,'EUR','USD','CASH'):
   raise PermissionError('Exact physical cash pair required')
  self.subscription=rows[0]
  details=await self.bounded(self.ib.reqContractDetailsAsync(self.subscription))
  if len(details)!=1:raise PermissionError('Unique FX details required')
  self.ib.reqMarketDataType(1);self.ticker=self.ib.reqMktData(self.subscription,'',False,False)
  end=self.clock()+15
  while self.clock()<end:
   if len(self.quote_times)==2 and self.ticker.marketDataType==1:return details[0]
   await asyncio.sleep(.1)
  raise TimeoutError('Fresh EURUSD quote unavailable')
 def quote(self):return dict(bid=self.ticker.bid,ask=self.ticker.ask,data_type=self.ticker.marketDataType,**self.quote_times)
 def order(self,p):
  from ib_async import LimitOrder
  return LimitOrder('SELL',p['quantity'],float(p['limit_price']),account=ACCOUNT,tif='DAY',outsideRth=False,orderRef=p['order_ref'],transmit=True)
 async def estimate(self,p):
  estimate=await asyncio.wait_for(self.ib.whatIfOrderAsync(self.subscription,self.order(p)),12)
  if (estimate.commissionCurrency!='EUR' or Decimal(str(estimate.initMarginChange))!=0
      or Decimal(str(estimate.maintMarginChange))!=0 or estimate.warningText):
   raise PermissionError('No-margin EUR-denominated broker fee estimate required')
  return estimate.commission
 async def cashbook(self):
  b=await fetch_paper_cashbook(self.ib,ACCOUNT);b['observed_at']=datetime.now(timezone.utc).isoformat();return b
 async def submit(self,p):
  trade=self.ib.placeOrder(self.subscription,self.order(p))
  end=self.clock()+15
  while self.clock()<end and trade.orderStatus.status not in ('Filled','Inactive'):
   await asyncio.sleep(.1)
  if trade.orderStatus.status!='Filled':
   # A partial/pending result is never retried or cancelled by this scope.
   return {'status':'UNKNOWN','order_id':trade.order.orderId,'perm_id':trade.order.permId,'native_status':trade.orderStatus.status}
  end=self.clock()+8
  while self.clock()<end and (not trade.fills or any(not f.commissionReport.execId for f in trade.fills)):
   await asyncio.sleep(.1)
  fills=trade.fills
  if not fills or any(not f.commissionReport.execId or f.commissionReport.currency!='EUR'
     or f.execution.acctNumber!=ACCOUNT or f.contract.conId!=12087792
     or f.execution.permId!=trade.order.permId or trade.order.permId<=0
     or f.execution.side!='SLD' for f in fills):raise PermissionError('Exact fill/commission lineage unavailable')
  fee=sum(Decimal(str(f.commissionReport.commission)) for f in fills)
  after=await self.cashbook();snapshot=await self.snapshot()
  return {'status':'FILLED','order_id':trade.order.orderId,'perm_id':trade.order.permId,'filled_eur':str(trade.orderStatus.filled),
          'commission_eur':str(fee),'execution_ids':[f.execution.execId for f in fills],'snapshot':snapshot,'cashbook':after}


def verified_snapshot(b,s):
 if (s.get('account')!=ACCOUNT or not s.get('complete') or set(s.get('ends',[]))!={'positions','orders','completed_orders','executions'}
     or not 0<=b.clock()-s.get('oldest_end_at',0)<=5):raise PermissionError('Fresh complete global readback required')
 if any(o.get('sec_type')=='CASH' for o in s['orders']):raise PermissionError('Existing cash-pair order must be reconciled')
 if any(o.get('side')=='BUY' for o in s['orders']):raise PermissionError('Active buy funding reservations require reconciliation before FX')

def stock_positions(s):return sorted((p['account'],p['con_id'],p['quantity']) for p in s['positions'] if p.get('sec_type')!='CASH')

def inherited_orders(s):
 return sorted(tuple(str(o.get(k,'')) for k in ('account','perm_id','con_id','symbol','side','order_type','quantity','remaining','aux_price','tif','transmit'))
               for o in s['orders'] if o.get('sec_type')!='CASH')


async def run(root):
 scope=json.loads((root/'runtime/cash-conversion-scope.json').read_text());actual=context();validate(scope,actual,root,now=time.time())
 coordinator=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
 if any(r[1]=='order' for r in coordinator.uncertainties()):raise PermissionError('Uncertain operation; no FX replay')
 b=Broker();ref=None;operation=None;result=None
 try:
  await b.connect();before=await b.snapshot();verified_snapshot(b,before)
  details=await b.reference()
  from trading.paper_acceptance import check_session
  check_session(details.liquidHours,details.timeZoneId)
  book=await b.cashbook()
  candidate=plan(scope,book,b.quote(),min_tick=details.minTick,commission_eur=5,now=b.clock())
  estimated=await b.estimate(candidate)
  pre_submit=await b.snapshot();verified_snapshot(b,pre_submit)
  if stock_positions(pre_submit)!=stock_positions(before):raise PermissionError('Portfolio changed during FX preflight')
  # Preserve exact fee-estimated quantity/limit, checking current marketability,
  # source cash age and hard EUR cash before the single actual placement.
  fresh_quote=b.quote()
  plan(scope,book,fresh_quote,min_tick=details.minTick,commission_eur=estimated,now=b.clock())
  if Decimal(str(fresh_quote['bid']))<Decimal(candidate['limit_price']):raise PermissionError('Estimated FX limit no longer marketable')
  validate(scope,actual,root,now=b.clock())
  ref=reserve(root,candidate);operation='order:'+ref
  if not coordinator.begin_operation(operation,'order',candidate):
   finish(root,ref,'REJECTED',{'reason':'Another uncertain operation; no FX transport'})
   raise PermissionError('Uncertain operation')
  settled=False
  try:
   result=await b.submit(candidate)
   if result.get('status')=='FILLED':
    verified_snapshot(b,result['snapshot'])
    cash_at=datetime.fromisoformat(result['cashbook']['observed_at'])
    if cash_at.tzinfo is None or not 0<=b.clock()-cash_at.timestamp()<=10:raise PermissionError('Post-fill cash evidence stale')
   confirmed=(result.get('status')=='FILLED' and stock_positions(result['snapshot'])==stock_positions(before)
       and inherited_orders(result['snapshot'])==inherited_orders(before)
       and reconcile(candidate,result['cashbook'],filled_eur=result['filled_eur'],commission_eur=result['commission_eur'],
             open_scope_orders=[o for o in result['snapshot']['orders'] if o['order_ref']==ref],execution_ids=result['execution_ids']))
   status='FILLED' if confirmed else 'UNKNOWN'
   finish(root,ref,status,{'plan':candidate,'native':result})
   settled=True
   coordinator.finish_operation(operation,'CONFIRMED' if confirmed else 'UNKNOWN')
   publication=publish_legacy_cashbook(root,result['cashbook']) if confirmed else 'NOT_CONFIRMED_NOT_PUBLISHED'
   return {'state':status,'order_ref':ref,'plan':candidate,'native':result,'cashbook_publication':publication,'estimated_commission_eur':str(estimated),'grants_stock_entry_permission':False}
  except BaseException as exc:
   if not settled:
    try:finish(root,ref,'UNKNOWN',{'plan':candidate,'error_type':type(exc).__name__})
    finally:coordinator.finish_operation(operation,'UNKNOWN')
   raise
 finally:b.close()


def main():
 os.umask(0o077);root=Path.home()/'.local/state/openclaw'
 with monitoring_service('cash-conversion',root):
  result=asyncio.run(asyncio.wait_for(run(root),110));RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('CASH_CONVERSION','DEGRADED',freshness='STALE',reason=result['state'],enabled=False,grants_stock_entry_permission=False);result['observed_at']=datetime.now(timezone.utc).isoformat()
  p=root/'runtime/cash-conversion.latest.json';temp=p.with_suffix('.tmp')
  with temp.open('w') as f:json.dump(result,f,allow_nan=False);f.flush();os.fsync(f.fileno())
  temp.chmod(0o600);temp.replace(p);print(json.dumps(result,ensure_ascii=False))
 return 0

if __name__=='__main__':raise SystemExit(main())
