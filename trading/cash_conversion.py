"""Finite own-cash EUR->USD funding, separate from stock entry permission."""
from contextlib import closing
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
import hashlib,json,sqlite3

ACCOUNT='DUQ503649'
SCOPE='cash-funding-20261109-v1'


def validate(scope,actual,root,*,now):
 if (scope.get('id')!=SCOPE or scope.get('approved') is not True or scope.get('account')!=ACCOUNT
     or scope.get('environment')!='PAPER' or scope.get('action')!='CASH_FUNDED_EUR_TO_USD_ONLY'
     or scope.get('max_eur_spend')!=65000 or scope.get('target_usd_cash')!=2010 or scope.get('fee_reserve_eur')!=5
     or scope.get('max_submissions')!=1 or scope.get('grants_stock_entry_permission') is not False
     or any(not actual.get(k) or scope.get(k)!=actual[k] for k in ('commit','branch','code_root','state_root'))):
  raise PermissionError('Exact finite cash-funded scope required')
 at=datetime.fromisoformat(scope['expires_at'])
 if at.tzinfo is None or not 0<at.timestamp()-now<=7200:raise PermissionError('Finite FX scope expired')
 policy=json.loads((root/'runtime/funding-policy.json').read_text())
 if not (policy.get('approved') is True and policy.get('account')==ACCOUNT and policy.get('environment')=='PAPER'
         and policy.get('mode')=='CASH_ONLY_NO_NEW_BORROWING' and policy.get('automatic_fx_approved') is True
         and policy.get('allow_new_currency_debit') is False):raise PermissionError('Existing own-cash FX authority required')
 if set(scope.get('preserved_files',{}))!={'production.json','PAUSED','runtime/MAINTENANCE'}:raise PermissionError('Preserved gates required')
 for n,h in scope['preserved_files'].items():
  if hashlib.sha256((root/n).read_bytes()).hexdigest()!=h:raise PermissionError('Global gate drift')


def plan(scope,book,quote,*,min_tick,commission_eur,now):
 def d(x):
  if isinstance(x,bool):raise PermissionError('Boolean monetary value')
  v=Decimal(str(x))
  if not v.is_finite():raise PermissionError('Finite currency evidence required')
  return v
 if book.get('account')!=ACCOUNT or book.get('source')!='BROKER_API' or book.get('base_currency')!='EUR':raise PermissionError('Exact fresh EUR/USD broker cashbook required')
 at=datetime.fromisoformat(book['observed_at'])
 if at.tzinfo is None or not 0<=now-at.timestamp()<=10 or not {'USD','EUR'}<=set(book.get('requested_currencies',[])):
  raise PermissionError('Both currencies must have fresh explicit end markers')
 usd,eur=d(book['currencies']['USD']['amount']),d(book['currencies']['EUR']['amount'])
 if usd>=0:raise PermissionError('No inherited USD deficit; do not allocate arbitrary extra currency')
 bid,ask,tick=d(quote['bid']),d(quote['ask']),d(min_tick)
 if quote.get('data_type')!=1 or not 0<bid<=ask<10 or ask/bid-1>Decimal('.001') or tick<=0:raise PermissionError('Fresh tight real EURUSD quote required')
 for key in ('bid_at','ask_at'):
  if not 0<=Decimal(str(now))-d(quote[key])<=3:raise PermissionError('Stale/future FX quote')
 fee=d(commission_eur)
 if not 0<=fee<=scope['fee_reserve_eur']:raise PermissionError('Finite broker fee estimate within scope required')
 limit=((bid-tick*2)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
 if limit<=0:raise PermissionError('Positive cash exchange limit required')
 quantity=((-usd+scope['target_usd_cash'])/limit).to_integral_value(rounding=ROUND_CEILING)
 if not 0<quantity+scope['fee_reserve_eur']<=scope['max_eur_spend'] or quantity+scope['fee_reserve_eur']>eur:raise PermissionError('Own EUR cash/spend cap insufficient')
 return dict(account=ACCOUNT,symbol='EUR',currency='USD',sec_type='CASH',con_id=12087792,exchange='IDEALPRO',side='SELL',
             quantity=int(quantity),limit_price=str(limit),before_usd=str(usd),before_eur=str(eur),fee_reserve_eur=scope['fee_reserve_eur'],
             expected_min_usd_credit=str(quantity*limit),order_ref=SCOPE+':EURUSD',grants_stock_entry_permission=False)


def reserve(root,p):
 with closing(sqlite3.connect(root/'trading_audit.sqlite3',timeout=2)) as c,c:
  c.execute('BEGIN IMMEDIATE')
  c.execute('CREATE TABLE IF NOT EXISTS cash_conversion_attempts(ref TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL)')
  if c.execute('SELECT 1 FROM cash_conversion_attempts').fetchone():raise PermissionError('FX occurrence already attempted; never replay')
  if c.execute("SELECT 1 FROM order_requests WHERE status IN ('RESERVED','STARTED','UNKNOWN','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED','PAPER_PENDING_CONFIRMATION') LIMIT 1").fetchone():raise PermissionError('Uncertain/pending intent')
  encoded=json.dumps(p,sort_keys=True);ref=p['order_ref']
  c.execute('INSERT INTO cash_conversion_attempts VALUES (?,?,?)',(ref,'STARTED',encoded))
  c.execute('INSERT INTO order_requests VALUES (?,?,?,?,?,?)',(ref,datetime.now(timezone.utc).isoformat(),'PAPER_CASH_CONVERSION','STARTED',encoded,'Finite own-cash funding, not strategy return'))
 return ref


def finish(root,ref,status,evidence):
 if status not in ('FILLED','REJECTED','UNKNOWN'):raise ValueError('Explicit FX result required')
 with closing(sqlite3.connect(root/'trading_audit.sqlite3',timeout=2)) as c,c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT status,payload FROM cash_conversion_attempts WHERE ref=?',(ref,)).fetchone()
  if not row or row[0]!='STARTED':raise PermissionError('Immutable started FX intent required')
  c.execute('UPDATE cash_conversion_attempts SET status=?,payload=? WHERE ref=?',(status,json.dumps({'plan':json.loads(row[1]),'evidence':evidence},sort_keys=True),ref))
  c.execute('UPDATE order_requests SET status=?,details=? WHERE idempotency_key=?',(status,json.dumps(evidence,sort_keys=True),ref))


def reconcile(p,after,*,filled_eur,commission_eur,open_scope_orders,execution_ids):
 try:
  filled=Decimal(str(filled_eur));fee=Decimal(str(commission_eur));eur=Decimal(after['currencies']['EUR']['amount']);usd=Decimal(after['currencies']['USD']['amount'])
  if (not all(x.is_finite() for x in (filled,fee,eur,usd)) or after.get('account')!=ACCOUNT
      or after.get('source')!='BROKER_API' or not {'USD','EUR'}<=set(after.get('requested_currencies',[]))):return False
  debit=Decimal(p['before_eur'])-eur;credit=usd-Decimal(p['before_usd'])
  return bool(filled==p['quantity'] and 0<=fee<=p['fee_reserve_eur'] and eur>=0 and usd>=2000
       and abs(debit-filled-fee)<=Decimal('.10') and credit>=Decimal(p['expected_min_usd_credit'])-Decimal('.10')
       and not open_scope_orders and execution_ids and len(execution_ids)==len(set(execution_ids)))
 except (ValueError,KeyError,TypeError,ArithmeticError):return False
