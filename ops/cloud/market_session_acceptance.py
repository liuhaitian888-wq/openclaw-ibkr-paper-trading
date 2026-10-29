"""Passive T4-v2 acceptance evidence. No broker client, recovery owner or SMTP."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from trading.symbol_health import classify_symbol

SYMBOLS=('PFE','BAC','KO')

def ownership(root):
    """Read Linux process/lock evidence; no service calls or process control."""
    processes=[]
    for path in Path('/proc').glob('[0-9]*'):
        try:
            command=(path/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            if any(name in command for name in ('paper_safety_watch.py','paper_readback.py','collect_paper_evidence.py','market_session_probe.py','run_autonomous_trading_agent.py')):
                processes.append(dict(pid=int(path.name),command=command))
        except (OSError,ValueError):pass
    lock_owner=None
    try:
        inode=(root/'runtime/paper-safety.lock').stat().st_ino
        for line in Path('/proc/locks').read_text().splitlines():
            parts=line.split()
            if len(parts)>5 and parts[1]!='->' and parts[5].split(':')[-1]==str(inode):lock_owner=int(parts[4])
    except (OSError,ValueError):pass
    owners=[x['pid'] for x in processes if 'paper_safety_watch.py' in x['command']]
    return dict(processes=processes,lock_pid=lock_owner,production_owner_count=len(owners),
                single_owner_verified=len(owners)==1 and lock_owner==owners[0])

def read_source(root):
    manifest=json.loads((root/'production.json').read_text())
    if manifest.get('environment')!='PAPER' or manifest.get('account')!='DUQ503649':
        raise PermissionError('Exact existing Paper account required')
    with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
        c.execute('PRAGMA query_only=ON')
        with c:
            state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
            errors=[dict(observed=t,kind=k,payload=json.loads(p)) for t,k,p in c.execute(
                "SELECT observed,kind,payload FROM paper_callback_events WHERE kind IN ('error','history_gap') ORDER BY observed DESC LIMIT 100")]
    try:observer=json.loads((root/'reports/paper_strategy/latest.json').read_text())
    except (OSError,ValueError):observer={}
    return manifest,state,observer,errors

def evaluate(state,observer,now,regular):
    result={}
    for symbol in SYMBOLS:
        q=dict(state.get('quotes',{}).get(symbol,{}))
        q['data_type']=state.get('market_types',{}).get(symbol,q.get('data_type'))
        h=classify_symbol(q,now,session='REGULAR' if regular else 'CLOSED')
        o=observer.get('symbols',{}).get(symbol,{})
        ends=set(state.get('bars',{}).get(symbol,[]))
        history=state.get('history_evidence',{}).get(symbol,{})
        if history.get('complete') is True:ends.update(history.get('completed_ends',[]))
        ends.update(float(t) for t in o.get('completed_bar_ends',[]))
        latest=o.get('latest_completed_bar')
        if latest:
            try:ends.add(datetime.fromisoformat(latest).timestamp())
            except (ValueError,TypeError):pass
        ends=sorted(t for t in ends if t<=now)
        result[symbol]=dict(quote=q,health=h,bar_ends=ends,history_gaps=o.get('history_gaps'),
            history_count=o.get('history_bars'),raw_last_available=q.get('last') is not None,
            callback_age={k:now-q[k] if isinstance(q.get(k),(int,float)) else None for k in ('bid_at','ask_at','last_at')})
    return result

def verdict(samples,start,end):
    regular=[s for s in samples if start<=s['observed_at']<end]
    checks={};all_errors={}
    for s in samples:
        for e in s.get('new_errors',[]):all_errors[json.dumps(e,sort_keys=True)]=e
    for symbol in SYMBOLS:
        seen=set();bars=set();fresh=0;stale=0;max_stale_run=0;run=0
        mature=[s for s in regular if s['observed_at']>=start+300]
        fresh_bars=0;last_available=0;last_fresh=0;types={}
        for s in regular:
            d=s.get('symbols',{}).get(symbol,{})
            q=d.get('quote',{});h=d.get('health',{})
            if h.get('allows_realtime') and s.get('connected') and s.get('identity'):
                fresh+=1;run=0;seen.add((q.get('bid_at'),q.get('ask_at')))
            else:stale+=1;run+=1;max_stale_run=max(max_stale_run,run)
            actual_type=str(q.get('data_type'));types[actual_type]=types.get(actual_type,0)+1
            if q.get('last') is not None:
                last_available+=1
                if isinstance(q.get('last_at'),(int,float)) and 0<=s['observed_at']-q['last_at']<=5:last_fresh+=1
            available={t for t in d.get('bar_ends',[]) if isinstance(t,(int,float)) and math.isfinite(t) and start<=t<=s['observed_at']}
            bars.update(available)
            if s['observed_at']>=start+300 and available and 0<=s['observed_at']-max(available)<=65:fresh_bars+=1
        ordered=sorted(bars);longest=current=0;previous=None
        for t in ordered:
            current=current+1 if previous is not None and t-previous==60 else 1
            longest=max(longest,current);previous=t
        # Opening grace first five minutes; sustained failure still stays FAIL.
        adequate=len(mature)>=12
        bar_ratio=fresh_bars/len(mature) if mature else 0
        # Allow 65 seconds for the most recent completed-bar callback, but no
        # missing mature minute may be hidden by three old contiguous bars.
        first_expected=math.ceil((start+300)/60)*60
        last_expected=math.floor((max((s['observed_at'] for s in regular),default=start)-65)/60)*60
        missing=[t for t in range(int(first_expected),int(last_expected)+1,60) if t not in bars]
        ratio=fresh/len(regular) if regular else 0
        checks[symbol]=dict(quote_status='PENDING' if not adequate else 'PASS' if len(seen)>=3 and ratio>=.8 else 'FAIL',
            fresh_samples=fresh,stale_samples=stale,fresh_ratio=ratio,distinct_quote_pairs=len(seen),
            kline_status='PENDING' if not adequate else 'PASS' if longest>=3 and bar_ratio>=.8 and not missing else 'FAIL',
            mature_fresh_bar_samples=fresh_bars,mature_bar_fresh_ratio=bar_ratio,missing_completed_ends=missing,
            actual_market_data_types=types,last_available_samples=last_available,last_fresh_samples=last_fresh,
            last_timestamp_status='MISSING' if not last_available else 'OBSERVED_FRESH' if last_fresh else 'STALE_OR_UNVERIFIED',
            longest_contiguous_minutes=longest,observed_completed_ends=ordered,max_stale_sample_run=max_stale_run)
    recovery={}
    for code in (1100,1101,1102,10197):
        events=[e for e in all_errors.values() if e.get('payload',{}).get('code')==code]
        # A quiet market window is not an error-recovery acceptance.
        recovery[str(code)]=dict(status='PENDING',events=events,reason='No controlled or complete real error-to-recovery proof in passive samples')
    versions=sorted({s['source_commit'] for s in samples if s.get('source_commit')})
    version_changed=len(versions)>1
    version_status='PENDING' if not regular else 'PASS' if len(versions)==1 and all(s.get('source_commit') for s in regular) else 'FAIL'
    owner_status='PENDING' if not regular else 'PASS' if all(s.get('ownership',{}).get('single_owner_verified') is True for s in regular) else 'FAIL'
    data_status='PASS' if all(v['quote_status']==v['kline_status']=='PASS' for v in checks.values()) else 'FAIL' if any('FAIL' in (v['quote_status'],v['kline_status']) for v in checks.values()) else 'PENDING'
    return dict(symbols=checks,real_recovery=recovery,production_version_changed=version_changed,
        source_versions=versions,version_status=version_status,owner_status=owner_status,
        broker_requests_sent=0,orders_sent=0,regular_samples=len(regular),
        overall='FAIL' if version_changed or version_status=='FAIL' or owner_status=='FAIL' or any('read_error' in s for s in samples) else data_status,
        scope='Quote/K-line observation only; overall does not close recovery or production retry gates')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--production-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--regular-start',type=float,required=True);p.add_argument('--regular-end',type=float,required=True)
    p.add_argument('--seconds',type=float,default=1800);p.add_argument('--interval',type=float,default=5)
    a=p.parse_args();root=a.production_root.resolve(strict=True);out=a.output.resolve()
    if not (0<a.seconds<=2400 and 1<=a.interval<=60 and a.regular_start<a.regular_end):p.error('Bounded duration/cadence/window required')
    if out==root or root in out.parents or out in root.parents or out.is_symlink():p.error('Output must be isolated from production')
    os.umask(0o077);out.mkdir(parents=True,exist_ok=False)
    samples=[];initial=time.time();deadline=time.monotonic()+a.seconds
    with (out/'reader.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            now=time.time()
            try:
                m,s,o,errors=read_source(root)
                row=dict(observed_at=now,source_commit=m.get('commit'),account=m['account'],environment=m['environment'],
                    connected=s.get('connected'),identity=s.get('identity'),fault=s.get('fault'),heartbeat=s.get('last_server_reply'),
                    legacy_retries=s.get('retries'),upstream_connected=s.get('upstream_connected'),
                    ownership=ownership(root),
                    symbols=evaluate(s,o,now,a.regular_start<=now<a.regular_end),
                    new_errors=[e for e in errors if e['observed']>=initial],source_access='SQLITE_READ_ONLY',broker_requests_sent=0)
            except Exception as exc:row=dict(observed_at=now,read_error=type(exc).__name__+': '+str(exc),symbols={})
            samples.append(row)
            with (out/'samples.jsonl').open('a') as f:f.write(json.dumps(row,sort_keys=True)+'\n')
            summary=verdict(samples,a.regular_start,a.regular_end)
            summary.update(started_at=initial,updated_at=now,completed=False,read_errors=sum('read_error' in r for r in samples))
            tmp=out/'summary.tmp';tmp.write_text(json.dumps(summary,indent=2));tmp.replace(out/'summary.json')
            if time.monotonic()+a.interval>deadline:break
            time.sleep(a.interval)
        summary.update(completed=True,ended_at=time.time(),sample_count=len(samples))
        (out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,sort_keys=True))
    return 1 if summary['read_errors'] else 0

if __name__=='__main__':raise SystemExit(main())
