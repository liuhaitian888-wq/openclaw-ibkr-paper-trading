"""Bounded, read-only execution inventory. This report never grants permission."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import sqlite3
import time
from .database_console import contained

ENDS={'positions','orders','completed_orders','executions'}
ACCOUNT='DUQ503649'


def read_json(root, name):
    p=contained(root,name)
    if p.stat().st_size>500_000:raise ValueError('Bounded state document required')
    value=json.loads(p.read_text())
    if not isinstance(value,dict):raise ValueError('Object required')
    return value


def database_read(root,name,fn):
    p=contained(root,name)
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
        c.execute('PRAGMA query_only=ON');deadline=time.monotonic()+.25
        c.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
        return fn(c)


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def inventory(state, *, verified):
    rows=[];orders=list(state.get('orders',{}).values())
    positions=state.get('positions',{}) if verified else {**state.get('last_positions',{}),**state.get('positions',{})}
    for symbol,quantity in sorted(positions.items()):
        if not finite(quantity) or not quantity:continue
        native=[o for o in orders if o.get('symbol')==symbol and not o.get('completed') and o.get('status') not in ('Filled','Cancelled','ApiCancelled','Inactive')]
        contract=state.get('contracts',{}).get(symbol,{})
        valid=[o for o in native if o.get('account')==ACCOUNT and o.get('side')=='SELL' and o.get('order_type')=='STP'
               and o.get('status') in ('Submitted','PreSubmitted') and o.get('transmit') is True
               and not o.get('parent_id') and not o.get('oca_group') and o.get('perm_id')
               and contract.get('currency')=='USD' and contract.get('sec_type')=='STK' and contract.get('con_id')
               and all(o.get(k)==contract[k] for k in ('currency','sec_type','con_id'))
               and finite(o.get('remaining')) and o['remaining']>0 and finite(o.get('aux_price')) and o['aux_price']>0]
        covered=sum(o['remaining'] for o in valid)
        unique=len({o['perm_id'] for o in valid})==len(valid)
        status='PROTECTED' if verified and quantity>0 and covered==quantity and unique else 'UNPROTECTED' if verified and not native else 'REVIEW_REQUIRED'
        if not verified:status='STALE_OR_UNVERIFIED'
        rows.append({'symbol':symbol,'quantity':quantity,'protection':status,'simple_stop_covered_quantity':covered if verified else None,
                     'orders':[{k:o.get(k) for k in ('account','side','order_type','remaining','aux_price','status','perm_id','client_id','order_ref')} for o in native],
                     'strategy_ownership':'NOT_ASSUMED'})
    return rows


def collect(root, *, now=None):
    root=Path(root);now=time.time() if now is None else now;errors=[]
    def load(name):
        try:return read_json(root,name)
        except (OSError,ValueError,TypeError):errors.append(name);return {}
    manifest=load('production.json')
    try:
        row=database_read(root,'runtime/recovery.sqlite3',lambda c:c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone())
        state=json.loads(row[0]) if row else {}
        if not isinstance(state,dict):raise ValueError('Broker state object required')
    except (OSError,ValueError,TypeError,sqlite3.Error):state={};errors.append('broker_state')
    age=now-state.get('last_server_reply',0) if finite(state.get('last_server_reply')) else None
    verified=(state.get('identity') is True and state.get('connected') is True and state.get('upstream_connected') is True
              and state.get('dirty') is False and set(state.get('ends',[]))==ENDS and age is not None and 0<=age<=10)
    try:
        uncertain=database_read(root,'runtime/recovery.sqlite3',lambda c:c.execute("SELECT count(*) FROM operation_attempts WHERE kind='order' AND status IN ('STARTED','UNKNOWN')").fetchone()[0])
        pending=database_read(root,'trading_audit.sqlite3',lambda c:c.execute("SELECT count(*) FROM order_requests WHERE status IN ('RESERVED','STARTED','UNKNOWN','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED')").fetchone()[0])
    except (OSError,ValueError,sqlite3.Error):uncertain=pending=None;errors.append('operation_ledgers')
    holdings=inventory(state,verified=verified);strategy=manifest.get('strategy_configuration',{});safety=manifest.get('safety',{})
    from .telegram_gate import current
    try:controls=current(root)
    except (OSError,ValueError,TypeError,KeyError):controls=None;errors.append('risk_controls')
    checks=[]
    def check(key,passed,kind,detail):checks.append({'gate':key,'state':'PASS' if passed else 'BLOCKED','category':kind,'detail':detail})
    check('BROKER_READBACK',verified,'RUNTIME','Exact Paper identity; all four readback ends; non-dirty; server reply <=10s')
    check('NO_UNCERTAIN_ORDERS',uncertain==0 and pending==0,'RUNTIME',{'operation_attempts':uncertain,'pending_order_requests':pending})
    check('MANIFEST_EXECUTION',manifest.get('ready') is True and manifest.get('mode')!='SAFE_MONITOR_ONLY','APPROVAL','Formal commit/path/account deployment still required; this report never publishes it')
    check('STRATEGY_EXECUTION',strategy.get('execution_approved') is True,'APPROVAL',{'observed_configuration':strategy,'execution_symbols':manifest.get('market_symbols',[])})
    check('OPERATOR_RELEASE',not (root/'PAUSED').exists() and not (root/'runtime/MAINTENANCE').exists(),'APPROVAL','Existing operator pause/maintenance preserved; environment kill/transmit/session gates also apply')
    check('CANONICAL_AND_OWNERSHIP',manifest.get('canonical_current_state_verified') is True and safety.get('reconciled') is True and safety.get('ownership_verified') is True,'ENGINEERING','Broker quantities are not strategy ownership or canonical lifecycle reconciliation')
    check('PORTFOLIO_PROTECTION',verified and all(x['protection']=='PROTECTED' for x in holdings),'APPROVAL_AND_ENGINEERING',{'uncovered':[x['symbol'] for x in holdings if x['protection']!='PROTECTED'],'policy':'Preserve existing orders; do not adopt, sell or add stops without owner scope'})
    currency=load('runtime/currency-book.latest.json')
    funding=load('runtime/funding-policy.json')
    check('FUNDING_POLICY',funding.get('approved') is True and funding.get('mode')=='CASH_ONLY_NO_NEW_BORROWING' and funding.get('allow_new_currency_debit') is False,'APPROVAL',{'mode':funding.get('mode'),'requirement':'Owner confirmed own cash only, no new overdraft or financing. FX is not automatically authorized.'})
    try:
        from decimal import Decimal
        usd=Decimal(currency['currencies']['USD']['amount']);cash_at=datetime.fromisoformat(currency['observed_at'])
        cash_ready=usd.is_finite() and usd>0 and cash_at.tzinfo is not None and 0<=now-cash_at.timestamp()<=10
    except (KeyError,ValueError,TypeError,ArithmeticError):cash_ready=False
    check('USD_CASH_AVAILABLE',cash_ready,'RUNTIME',{'observed_USD':currency.get('currencies',{}).get('USD'),'observed_at':currency.get('observed_at'),'requirement':'Fresh positive USD cash, all buy reservations and explicit fee reserve must be checked by actual executor. EUR available funds are not USD cash.'})
    check('PORTFOLIO_RISK',safety.get('risk_allowed') is True and safety.get('risk_isolatable') is True,'APPROVAL_AND_ENGINEERING','Fresh marks, external holdings/open buys, fee/FX/funding and scoped limits must be checked by the actual executor')
    check('NUMERIC_DOCUMENT',controls is not None,'RUNTIME','Valid additive control document does not imply complete portfolio risk verification')
    check('LIMITS_CONFIRMED',bool(controls and controls['revision']>0 and all(v is not None for v in controls['settings'].values())),'APPROVAL','Owner-set finite QMAX/OMAX/RMAX/SMAX/GMAX; template examples are not applied limits')
    scopes=state.get('pause_scopes',{});decisions=scopes.get('decisions',{}).get('classic_conservative_trend',{})
    check('LIVE_DATA_AND_SYMBOL_GATES',bool(decisions) and all(d.get('market_allowed') is True for d in decisions.values()),'RUNTIME','Market hours, actual fresh bid/ask and complete contiguous bars; closed market remains blocked')
    check('AUTOMATIC_EXECUTION_ACCEPTANCE',False,'ENGINEERING','Observed cloud strategy is MONITOR_ONLY. Finite cancel/fill/close 3/3 does not verify sustained signal->approved executor->partial-fill protection->restart reconciliation. No automatic activation from this report.')
    check('PERFORMANCE_T0',False,'APPROVAL_AND_ENGINEERING','Draft only until scoped strategy inventory, fresh NAV/cash/FX/fees and start event are fixed; factual collection continues')
    return {'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'account':ACCOUNT,'environment':'PAPER',
            'mode':'READ_ONLY_READINESS_REPORT','grants_trading_permission':False,'automatic_trading_ready':False,
            'broker_state_verified':verified,'server_reply_age_seconds':age,'holdings':holdings,'checks':checks,'risk_controls':controls,
            'unavailable_evidence':errors,'source':'Existing Paper owner and local control/operation ledgers; no broker request',
            'limitations':['Snapshot, not an execution permission','No live net liquidation/cash/FX or market value inferred from quantities','Execution service health and per-order production guards remain mandatory']}


def message(data, *, holdings_only=False):
    lines=['Paper holdings · '+data['account'] if holdings_only else 'Paper readiness · BLOCKED',data['observed_at']]
    if not data['broker_state_verified']:lines.append('⚠️ Broker snapshot stale/incomplete; quantities are last observed, not current confirmation.')
    lines.extend(x['symbol']+' '+format(x['quantity'],'g')+' · '+x['protection'] for x in data['holdings'])
    if not holdings_only:lines.extend(x['gate']+' · '+x['state'] for x in data['checks'])
    for x in data['holdings']:
        for o in x['orders']:lines.append(x['symbol']+' '+str(o['side'])+' '+str(o['order_type'])+' '+str(o['remaining'])+' @ '+str(o['aux_price'])+' · '+str(o['status']))
    lines.append('Read-only. No orders sent/cancelled; no pause or approval changed.')
    return '\n'.join(lines)
