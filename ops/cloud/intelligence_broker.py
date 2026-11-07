"""Bounded existing IBKR news adapter, with no price subscriptions or order methods."""
import asyncio
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.incidents import IncidentStore
from reporting.intelligence import initialize,held_symbols,paper_state,ingest,broker_records
from reporting.recovery import RecoveryCoordinator
from trading.news_feed import collect


async def batch(symbols,account,callback):
    from ib_async import IB,Stock
    completed=[]
    try:
        async with asyncio.timeout(150):
            for symbol in symbols:
                result=await collect(IB(),Stock,expected_account=account,symbol=symbol)
                completed.append(result);callback(result)
    except TimeoutError:pass
    return completed


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    policy=json.loads((root/'runtime/intelligence-policy.json').read_text())
    if policy.get('approved') is not True or policy.get('grants_trading_permission') is not False:raise PermissionError('Read-only policy required')
    config_path=Path.home()/'.config/openclaw/paper-observer.json'
    if config_path.stat().st_mode&0o077:raise PermissionError('Private broker identity required')
    account=json.loads(config_path.read_text())['expected_account']
    if account!='DUQ503649':raise PermissionError('Exact approved Paper identity required')
    # Same kernel lock as the previously reviewed one-shot news collector.
    with monitoring_service('ibkr-news-probe',root):
        archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive)
        store=IncidentStore(root/'runtime/recovery.sqlite3');symbols=held_symbols(paper_state(root))
        # Explicit approved watchlist extends beyond current holdings; no strategy enablement.
        config=json.loads((Path.home()/'.config/openclaw/intelligence.json').read_text())
        from reporting.research_universe import effective_symbols
        symbols=effective_symbols(root,config,paper_state(root))
        history=root/'observations/news';history.mkdir(parents=True,exist_ok=True)
        def received(result):
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');name=stamp+'-'+result['symbol']+'.json'
            (history/name).write_text(json.dumps(result,indent=2))
            for record in broker_records(result):
                ingest(archive,store,record,now=time.time(),armed_at=policy['armed_at'])
            latest=root/'runtime/news.latest.json';tmp=latest.with_suffix('.intelligence.tmp');tmp.write_text(json.dumps(result,indent=2));tmp.replace(latest)
        results=asyncio.run(batch(symbols,account,received)) if symbols else []
        verified=bool(symbols) and len(results)==len(symbols) and all(r['news_usable'] for r in results)
        status={'observed_at':datetime.now(timezone.utc).isoformat(),'symbols':symbols,'completed_symbols':[r['symbol'] for r in results],
                'per_symbol':[{k:r[k] for k in ('symbol','status','news_usable','identity_verified','live_stream_verified')} for r in results],
                'full_feed_streaming_verified':False,'state':'SCOPED_RETRIEVAL_VERIFIED' if verified else 'PARTIAL_OR_UNAVAILABLE','grants_trading_permission':False}
        path=root/'runtime/intelligence-broker.latest.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(status,indent=2));tmp.replace(path)
        RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('INTELLIGENCE_BROKER','HEALTHY' if verified else 'DEGRADED',freshness='FRESH' if verified else 'UNKNOWN',enabled=True,reason='Scoped existing news adapter completed; streaming remains unverified',coverage=status)
        print(json.dumps(status));return 0


if __name__=='__main__':raise SystemExit(main())
