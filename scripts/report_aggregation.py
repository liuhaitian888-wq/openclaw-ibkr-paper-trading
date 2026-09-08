"""Read-only broker-ledger aggregation. No trading entry points are called."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from trading.production_paths import state_root_for
from contextlib import closing

import calendar
import json
import math
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BJ = ZoneInfo('Asia/Shanghai')
NY = ZoneInfo('America/New_York')
UTC = timezone.utc
TYPES = ('DAILY', 'WEEKLY', 'MONTHLY')



def stamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo else None
    except ValueError:
        # IB execution timestamps: explicit timezone required, never host-local.
        try:
            parts = str(value).split()
            zone = ZoneInfo(parts[2]) if len(parts) == 3 else None
            return datetime.strptime(' '.join(parts[:2]), '%Y%m%d %H:%M:%S').replace(tzinfo=zone).astimezone(UTC) if zone else None
        except (ValueError, KeyError):
            return None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and abs(n) < 1e100 else None
    except (ValueError, TypeError):
        return None


def metric(value=None, source='', as_of=None, status=None):
    return {'value': value, 'status': status or ('MISSING' if value is None else 'AVAILABLE'), 'source': source, 'as_of': as_of}


def read_json(path):
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def rows(con, table):
    if con is None:
        return None
    try:
        return [dict(r) for r in con.execute('SELECT * FROM ' + table)]
    except sqlite3.OperationalError:
        return None


def json_object(value):
    if isinstance(value, dict):
        return value
    try:
        d = json.loads(value or '{}')
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def trading_day(day):
    from trading.market_session import calendar_status, MarketSessionConfig
    return calendar_status(day, config=MarketSessionConfig()).is_trading_day is True


def last_complete_day(now):
    local = now.astimezone(NY)
    day = local.date() - timedelta(days=local.time() < time(20))
    while not trading_day(day):
        day -= timedelta(days=1)
    return day


def select_type(day, monthly_policy='first_day'):
    if monthly_policy not in ('first_day', 'month_end'):
        raise ValueError('Unknown monthly policy')
    monthly = day.day == (1 if monthly_policy == 'first_day' else calendar.monthrange(day.year, day.month)[1])
    return 'MONTHLY' if monthly else 'WEEKLY' if day.weekday() == 6 else 'DAILY'


def period_for(kind, now, monthly_policy='first_day'):
    if now.tzinfo is None or kind not in TYPES:
        raise ValueError('Aware time and valid report type required')
    report_day = now.astimezone(BJ).date()
    partial = False
    if kind == 'DAILY':
        start_day = last_complete_day(now)
        end_day = start_day + timedelta(days=1)
    elif kind == 'WEEKLY':
        # Shanghai Sunday morning is still NY Saturday; same Monday week anchor.
        start_day = report_day - timedelta(days=report_day.weekday())
        end_day = start_day + timedelta(days=6)
    else:
        first = report_day.replace(day=1)
        if monthly_policy == 'first_day':
            end_day = first
            start_day = (first - timedelta(days=1)).replace(day=1)
        else:
            start_day = first
            end_day = first.replace(day=calendar.monthrange(first.year, first.month)[1]) + timedelta(days=1)
            partial = True
    start = datetime.combine(start_day, time(), NY).astimezone(UTC)
    nominal_end = datetime.combine(end_day, time(), NY).astimezone(UTC)
    end = min(nominal_end, now.astimezone(UTC))
    last_session = end_day - timedelta(days=1)
    while not trading_day(last_session):last_session -= timedelta(days=1)
    sessions_complete = datetime.combine(last_session, time(20), NY).astimezone(UTC) <= now.astimezone(UTC)
    return {'start_utc': start.isoformat(), 'end_utc': end.isoformat(), 'timezone': NY.key,
            'start_date': start_day.isoformat(), 'end_date_exclusive': end_day.isoformat(),
            'partial': partial or not sessions_complete, 'calendar_period_complete': end >= nominal_end, 'sessions_complete': sessions_complete}


def covers(coverage, name, start, end, account):
    return any(r.get('complete') is True and r.get('account') == account and
               stamp(r.get('start_utc')) is not None and stamp(r.get('end_utc')) is not None and
               stamp(r['start_utc']) <= start and stamp(r['end_utc']) >= end
               for r in coverage.get(name, []) if isinstance(r, dict))


def within(row, key, start, end):
    ts = stamp(row.get(key))
    return ts is not None and start <= ts < end


def real_row(row):
    raw = json_object(row.get('raw_json') or row.get('payload_json'))
    source = str(row.get('source_type') or raw.get('source_type') or '').upper()
    return source not in ('SIMULATED', 'SIMULATION', 'DRY_RUN', 'MOCK', 'TEST')


def aggregate_activity(con, start, end, account, coverage):
    result = {k: metric(source='broker ledger') for k in ('fills','shares_traded','turnover','buy_turnover','sell_turnover','commissions','orders_submitted','filled_orders','cancelled_orders','rejected_orders')}
    ledger = rows(con, 'executions')
    complete = covers(coverage, 'executions', start, end, account)
    if any(r.get('account') == account and stamp(r.get('executed_at')) is None for r in ledger or []):
        complete = False
    if not account:
        return {**result, 'state': 'MISSING', 'coverage_complete': False, 'currencies': {}}
    chosen = {}
    for r in ledger or []:
        if r.get('account') != account or not real_row(r) or not r.get('exec_id'):
            continue
        # IB correction exec IDs differ in the final numeric segment.
        eid = str(r['exec_id']); prefix, dot, suffix = eid.rpartition('.')
        correction = int(suffix) if dot and suffix.isdigit() else 0
        identity = prefix if dot and suffix.isdigit() else eid
        if identity not in chosen or correction > chosen[identity][0]:
            chosen[identity] = (correction, r)
    fills = [r for _, r in chosen.values() if within(r, 'executed_at', start, end)]
    result['fills'] = metric(len(fills) if ledger is not None else None, 'executions.exec_id', status='AVAILABLE' if complete else 'PARTIAL' if fills else 'MISSING')
    if not complete and not fills:
        result['fills']['value'] = None
    currencies = {}
    valid_shares = []; valid_turnover = True
    for r in fills:
        raw = json_object(r.get('raw_json')); contract = json_object(raw.get('contract'))
        sec_type = raw.get('sec_type') or raw.get('secType') or contract.get('secType')
        currency = raw.get('currency') or contract.get('currency')
        shares, price = number(r.get('shares')), number(r.get('price'))
        side = {'BOT':'BUY','SLD':'SELL'}.get(r.get('side'), r.get('side'))
        if shares is None or shares < 0 or sec_type != 'STK':
            valid_turnover = False; continue
        valid_shares.append(shares)
        if price is None or price < 0 or not currency or side not in ('BUY','SELL'):
            valid_turnover = False; continue
        bucket = currencies.setdefault(currency, {'BUY':0.0,'SELL':0.0})
        bucket[side] += shares * price
    if len(valid_shares) == len(fills) and (fills or complete):
        result['shares_traded'] = metric(sum(valid_shares), 'executions.shares (STK)', status='AVAILABLE' if complete else 'PARTIAL')
    if valid_turnover and (len(currencies) == 1 or complete and not fills):
        totals = next(iter(currencies.values()), {'BUY':0.0,'SELL':0.0})
        for key, val in [('turnover',sum(totals.values())),('buy_turnover',totals['BUY']),('sell_turnover',totals['SELL'])]:
            result[key] = metric(val, 'executions.shares * price', status='AVAILABLE' if complete else 'PARTIAL')
    selected_ids = {r['exec_id'] for r in fills}
    commission_map = {}
    for r in rows(con, 'commission_events') or []:
        if r.get('source_type') != 'REAL_IBKR':continue
        payload=json_object(r.get('payload_json')); payload=json_object(payload.get('payload',payload))
        eid=payload.get('exec_id') or payload.get('execId')
        if eid in selected_ids:
            commission_map[eid]=r
    comms=[number(r.get('commission')) for r in commission_map.values()]
    comm_currencies={r.get('currency') for r in commission_map.values()}
    if fills and len(commission_map)==len(fills) and None not in comms and len(comm_currencies)==1 and next(iter(comm_currencies)):
        result['commissions']=metric(sum(comms),'commission_events linked exec_id',status='AVAILABLE' if complete else 'PARTIAL')
    elif not fills and complete:
        result['commissions']=metric(0.0,'complete execution coverage: no fills')
    orders=rows(con,'broker_orders')
    if orders is not None:
        selected=[r for r in orders if r.get('account')==account and real_row(r)]
        for key, states in [('filled_orders',{'FILLED'}),('cancelled_orders',{'CANCELLED','APICANCELLED','CANCELED'}),('rejected_orders',{'REJECTED'})]:
            result[key]=metric(sum(within(r,'last_seen_at',start,end) and str(r.get('status') or r.get('canonical_status')).upper() in states for r in selected),'broker_orders final observed status',status='RECORDED')
        refs={r.get('order_ref') for r in selected if r.get('order_ref')}
        events=rows(con,'order_events')
        if events is not None:
            submitted={json_object(r.get('details')).get('order_id') for r in events if r.get('event_type')=='BROKER_ORDER_LINKED' and r.get('idempotency_key') in refs and within(r,'occurred_at',start,end)}
            submitted.discard(None)
            result['orders_submitted']=metric(len(submitted),'order_events.BROKER_ORDER_LINKED',status='RECORDED')
    state='NO_FILLS' if complete and not fills else 'FILLS' if fills else 'MISSING'
    return {**result,'state':state,'coverage_complete':complete,'currencies':currencies,
            'currency':next(iter(currencies)) if len(currencies)==1 else None,
            'commission_currency':next(iter(comm_currencies)) if len(comm_currencies)==1 else None}


def expected_days(start,end):
    day=start.astimezone(NY).date();out=[]
    while datetime.combine(day,time(),NY).astimezone(UTC)<end:
        if trading_day(day):out.append(day)
        day+=timedelta(days=1)
    return out


def aggregate_performance(con,start,end,account,coverage,extra_samples=()):
    from trading.market_session import calendar_status, MarketSessionConfig
    candidates={}
    for r in (rows(con,'daily_pnl_summary') or []) + list(extra_samples):
        if not account or r.get('account_id')!=account or r.get('stale')!=0 or not r.get('currency'):continue
        ts=stamp(r.get('pnl_sample_time_utc'))
        try:day=date.fromisoformat(r['trading_date'])
        except (ValueError,TypeError):continue
        close=calendar_status(day,config=MarketSessionConfig()).regular_close
        if not ts or ts>=end or ts.astimezone(NY).date()!=day or ts.astimezone(NY).time()<close:continue
        if day not in candidates or ts>stamp(candidates[day]['pnl_sample_time_utc']):candidates[day]=r
    days=expected_days(start,end)
    history=[{'date':d.isoformat(),**{k:number(candidates.get(d,{}).get(k)) for k in ['net_liquidation','daily_pnl','realized_pnl','unrealized_pnl']},'currency':candidates.get(d,{}).get('currency')} for d in days]
    complete=bool(days) and all(p['daily_pnl'] is not None for p in history) and len({p['currency'] for p in history})==1
    previous=start.astimezone(NY).date()-timedelta(days=1)
    while not trading_day(previous):previous-=timedelta(days=1)
    base=number(candidates.get(previous,{}).get('net_liquidation'))
    same_currency=bool(history) and candidates.get(previous,{}).get('currency')==history[-1]['currency']
    final=history[-1] if history else {}
    pnl=sum(p['daily_pnl'] for p in history) if complete else None
    delta=final.get('net_liquidation')-base if base is not None and final.get('net_liquidation') is not None and same_currency else None
    zero_flows=covers(coverage,'zero_external_cashflows',start,end,account)
    ret=pnl/base*100 if pnl is not None and base and same_currency and zero_flows else None
    complete_equity=bool(history) and all(p['net_liquidation'] is not None for p in history) and same_currency and base is not None and base>0
    drawdown=None
    if complete_equity and zero_flows:
        peak=base;drawdown=0.0
        for p in history:
            peak=max(peak,p['net_liquidation']);drawdown=max(drawdown,(peak-p['net_liquidation'])/peak*100)
    result={k:metric(v,'daily_pnl_summary fresh closing samples') for k,v in [('pnl',pnl),('return_pct',ret),('net_liquidation_change',delta),('realized_pnl',final.get('realized_pnl')),('unrealized_pnl',final.get('unrealized_pnl')),('max_drawdown_pct',drawdown)]}
    result.update(best_day=max(history,key=lambda p:p['daily_pnl']) if complete else None,worst_day=min(history,key=lambda p:p['daily_pnl']) if complete else None,
                  win_rate=metric(source='closed-trade attribution unavailable'),winning_trades=metric(),losing_trades=metric(),strategy_contribution=None,
                  complete_daily_pnl=complete,expected_trading_days=len(days),observed_pnl_days=sum(p['daily_pnl'] is not None for p in history),currency=final.get('currency'),trend=history)
    return result


def collect_report(root: Path,kind: str,now: datetime,monthly_policy='first_day',account_id=None):
    period=period_for(kind,now,monthly_policy);start=stamp(period['start_utc']);end=stamp(period['end_utc'])
    daily=read_json(state_root_for(root) / "reports/daily_trading/latest.json")
    state=read_json(state_root_for(root) / "reports/account_state/latest.json")
    snapshot=state.get('account_snapshot') or daily.get('account_snapshot') or {}
    runtime=read_json(state_root_for(root) / "reports/autonomous_agent/latest.json")
    coverage=read_json(state_root_for(root) / "reports/reporting_coverage.json")
    # Explicit exact account selection; a masked account may not select ledger rows.
    account_id=account_id or coverage.get('account')
    candidate=state.get('account_id') or read_json(state_root_for(root) / "reports/account/latest.json").get('account')
    if not account_id and isinstance(candidate,str) and candidate.startswith('DU') and candidate[2:].isdigit():account_id=candidate
    observation=read_json(state_root_for(root) / "reports/reporting_observation/latest.json")
    if not account_id and observation.get('source')=='REAL_IBKR' and observation.get('complete') is True and observation.get('account_id')==candidate and str(candidate).startswith('DU'):
        account_id=candidate  # Exact managedAccounts identity, not a guessed numeric account format.
    observed_account=observation.get('account',{}) if observation.get('source')=='REAL_IBKR' and observation.get('account_id')==account_id and observation.get('complete') is True else {}
    extra_samples=[read_json(p) for p in (state_root_for(root) / "reports/reporting_history").glob('*.json')]
    account={}
    for key in ['net_liquidation','total_cash_value','buying_power','available_funds','daily_pnl','realized_pnl','unrealized_pnl','gross_exposure','net_exposure']:
        field=json_object(observed_account.get(key) or snapshot.get(key));val=number(field.get('value'))
        account[key]=metric(val,field.get('source','account_snapshot'),field.get('source_timestamp'),field.get('freshness') if val is not None else 'MISSING')
        account[key]['currency']=field.get('currency')
        account[key]['account_fingerprint']=observation.get('account_fingerprint') if key in observed_account else None
    positions=snapshot.get('positions');account['positions']=metric(len(positions) if isinstance(positions,list) else None,'account_snapshot',snapshot.get('timestamp'))
    db=state_root_for(root) / "trading_audit.sqlite3";con=None
    try:
        if db.exists():
            con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row;con.execute('BEGIN')
        if not account_id and con:
            accounts={r.get('account') for r in rows(con,'executions') or [] if str(r.get('account','')).startswith('DU')}
            accounts.update(r.get('account') for r in rows(con,'broker_orders') or [] if str(r.get('account','')).startswith('DU'))
            if len(accounts)==1:account_id=accounts.pop()
        activity=aggregate_activity(con,start,end,account_id,coverage)
        performance=aggregate_performance(con,start,end,account_id,coverage,extra_samples)
        risk={}
        for name,table,column in [('risk_events','risk_events','timestamp'),('data_quality_incidents','quote_readiness_events','timestamp')]:
            data=rows(con,table)
            risk[name]=metric(sum(within(r,column,start,end) and (name!='data_quality_incidents' or r.get('execution_allowed')==0) for r in data) if data is not None else None,table+' recorded events',status='RECORDED' if data is not None else 'MISSING')
        risk['rejected_orders']=activity['rejected_orders']
        hist=[]
        for r in rows(con,'account_state_events') or []:
            payload=json_object(json_object(r.get('payload_json')).get('payload'))
            if payload.get('mode')!='PAPER' or payload.get('account_id')!=account_id or r.get('stale_flag')!=0 or not within(r,'timestamp_utc',start,end):continue
            snap=payload.get('account_snapshot',{})
            value=number(json_object(snap.get('gross_exposure')).get('value'))
            if value is not None:hist.append({'timestamp':r['timestamp_utc'],'gross_exposure':value,'coverage':snap.get('protective_order_coverage')})
        risk['max_exposure']=metric(max(p['gross_exposure'] for p in hist) if hist else None,'observed fresh account snapshots (sampled)')
        risk['protection_history']=hist
    finally:
        if con:con.close()
    q=snapshot.get('data_quality',{})
    from scripts.daily_visual_report import protection_summary
    text,status,_=protection_summary(positions or [],snapshot.get('protective_order_coverage') or [],snapshot)
    risk['protection']={'text':text,'status':status,'as_of':snapshot.get('timestamp'),'fresh':q.get('protection_coverage_fresh') is True}
    readiness=read_json(state_root_for(root) / "reports/account_execution_readiness/latest.json")
    attention=[]
    if not activity['coverage_complete']:attention.append('成交历史覆盖待核对 / Verify execution-history coverage')
    if not performance['complete_daily_pnl']:attention.append('收益历史不完整 / Complete the daily PnL history')
    if status!='PROTECTED':attention.append('核对保护覆盖 / Review protection coverage')
    if runtime.get('ibkr_connected') is False:attention.insert(0,'检查 IBKR 会话连接 / Check IBKR session')
    report={'schema_version':1,'report_type':kind,'report_date':now.astimezone(BJ).date().isoformat(),'trading_period':period,'generated_at':now.astimezone(UTC).isoformat(),
            'account':account,'activity':activity,'performance':performance,'risk':risk,'trend':performance['trend'][-7:] if kind=='DAILY' else performance['trend'],
            'attention':attention[:3],'paper_readiness':readiness.get('account_execution_ready',runtime.get('ready_for_orders')),
            'runtime_state':runtime.get('lifecycle_state','UNKNOWN'),'source_snapshot_at':snapshot.get('timestamp'),
            'provenance':{'database_available':db.exists(),'account_selected':bool(account_id),'source_root':str(root),'financial_policy':'missing is null; no inferred fills; recorded counts are not coverage proof'}}
    if kind=='DAILY':
        history_start=start-timedelta(days=6)
        if db.exists():
            with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as c, c:
                c.row_factory=sqlite3.Row;report['trend']=aggregate_performance(c,history_start,end,account_id,coverage,extra_samples)['trend']
    if kind=='MONTHLY':
        week=collect_report(root,'WEEKLY',now,monthly_policy,account_id)
        report['weekly_summary']={k:week[k] for k in ['trading_period','performance','activity','paper_readiness']}
    return report


def capture_financial_sample(root,now,account_id=None):
    """Archive genuine fresh account fields for future closing-day aggregation.

    Does not refresh trading/account state. Fields must share an account/currency
    and be observed within three minutes; timestamps are original source times.
    """
    state=read_json(state_root_for(root) / "reports/account_state/latest.json")
    snapshot=state.get('account_snapshot',{})
    account_report=read_json(state_root_for(root) / "reports/account/latest.json")
    account=account_id or state.get('account_id') or account_report.get('account')
    currency=account_report.get('currency')
    if not isinstance(account,str) or not account.startswith('DU') or not account[2:].isdigit() or not currency:return None
    sample={'account_id':account,'currency':currency,'stale':0,'source':'fresh_account_snapshot'}
    timestamps=[]
    for key in ('net_liquidation','daily_pnl','realized_pnl','unrealized_pnl'):
        field=json_object(snapshot.get(key));ts=stamp(field.get('source_timestamp'))
        valid=ts is not None and 0 <= (now-ts).total_seconds() <= 180 and field.get('freshness')=='FRESH'
        sample[key]=number(field.get('value')) if valid else None
        if valid and sample[key] is not None:timestamps.append(ts)
    if not timestamps or max(timestamps)-min(timestamps)>timedelta(seconds=180):return None
    ts=min(timestamps);sample.update(trading_date=ts.astimezone(NY).date().isoformat(),pnl_sample_time_utc=ts.isoformat())
    import hashlib
    text=json.dumps(sample,sort_keys=True);directory=state_root_for(root) / "reports/reporting_history";directory.mkdir(parents=True,exist_ok=True)
    path=directory/(hashlib.sha256(text.encode()).hexdigest()+'.json')
    if not path.exists():path.write_text(text+'\n')
    return sample
