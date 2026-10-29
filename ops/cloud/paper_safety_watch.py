"""Opt-in read-only continuous Paper order/protection monitor. No order transport."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from ops.cloud.alert_email import safety_email_owner
from trading.paper_safety_monitor import PaperSafetyMonitor, ACCOUNT, ENDS
from trading.paper_safety_client import PaperSafetyClient
from trading.tws_paper import _close_owned_client
from trading.paper_strategy_observer import PaperStrategyObserver


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    config_path=Path.home()/'.config/openclaw/paper-safety.json'
    if config_path.stat().st_mode & 0o077:
        raise PermissionError('Private monitor configuration must be 0600')
    cfg=json.loads(config_path.read_text())
    if cfg.get('account')!=ACCOUNT or cfg.get('environment')!='PAPER':
        raise PermissionError('Exact DUQ503649 Paper identity required')
    # Strategy metadata must be an already approved deployment fact, not a new
    # stop percentage or an execution permission manufactured by the monitor.
    manifest=json.loads((root/'production.json').read_text())
    strategy=manifest.get('strategy_configuration',{})
    if (manifest.get('account')!=ACCOUNT or manifest.get('environment')!='PAPER'
            or strategy.get('approved') is not True or strategy.get('bar_seconds')!=60
            or strategy.get('slow_window',0)<1
            or cfg.get('symbols')!=manifest.get('market_symbols')):
        raise PermissionError('Existing approved K-line configuration required')
    for name in ('trading_audit.sqlite3','runtime/recovery.sqlite3'):
        if not (root/name).is_file():
            raise PermissionError('Formal database must already be published')
    stopped=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stopped.set())
    with monitoring_service('paper-safety',root), safety_email_owner(root,stopped):
        monitor=PaperSafetyMonitor(root/'trading_audit.sqlite3',root/'runtime/recovery.sqlite3',
                                   symbols=cfg['symbols'],required_bars=strategy['slow_window'])
        observer=PaperStrategyObserver(cfg['symbols'],strategy,root/'reports/paper_strategy/latest.json',
            signal_configurations=manifest.get('signal_strategy_configurations'))
        attempts=0
        while not stopped.is_set():
            client=PaperSafetyClient(monitor,cfg['symbols'])
            client.strategy_observer=observer
            worker=None
            try:
                client.connect('127.0.0.1',4002,clientId=18770)
                worker=threading.Thread(target=client.run_loop,name='paper-safety-api',daemon=True)
                worker.start()
                if not client.ready.wait(10) or not client.accounts_ready.wait(10):
                    monitor.invalidate('AUTHENTICATION_OR_CONNECTION_REQUIRED')
                    raise RuntimeError('Human authentication or connection review required')
                monitor.begin(client.accounts)
                client.reconcile()
                client.subscribe()
                attempts=0
                last_sync=time.monotonic()
                last_heartbeat=0
                last_strategy=0
                last_recovery_poll=0
                while not stopped.wait(1):
                    if not worker.is_alive() or not client.isConnected() or not monitor.state['connected']:
                        raise RuntimeError('Order monitoring connection lost')
                    if time.monotonic()-last_heartbeat>=5:
                        client.reqCurrentTime()
                        last_heartbeat=time.monotonic()
                    if monitor.state['upstream_connected'] and monitor.clock()-monitor.state['last_server_reply']>10:
                        raise RuntimeError('Broker callback heartbeat missing')
                    with monitor.lock:
                        monitor._publish()
                        dirty=monitor.state['dirty']
                        complete=set(monitor.state['ends'])==ENDS
                    if monitor.state['upstream_connected'] and not complete and time.monotonic()-last_sync>=30 and not client.read_only_completed_orders_blocked:
                        raise RuntimeError('Incomplete readback; reconnect before another snapshot')
                    if time.monotonic()-last_strategy>=5:
                        with monitor.lock:
                            snapshot=monitor.snapshot()
                        with observer.lock:
                            observer.evaluate_catalog({s:dict(client.fields.get(i,{})) for i,s in client.tickers.items()},
                                snapshot,dict(monitor.state['positions']),monitor.clock())
                        for req_id,symbol in client.tickers.items():
                            with observer.lock:
                                observer.evaluate(symbol,dict(client.fields.get(req_id,{})),snapshot,monitor.clock())
                        last_strategy=time.monotonic()
                    # Keep monitoring during 10197. Only bounded data subscription
                    # retries; no Gateway process action, no account session takeover.
                    if time.monotonic()-last_recovery_poll>=5:
                        if monitor.state['upstream_connected']:client.retry_pending_initial()
                        client.backfill_history_gaps()
                        for action in monitor.poll_symbol_recovery():
                            client.retry_symbol_subscriptions(action['symbols'],bars_only=action['action']=='RESUBSCRIBE_BARS')
                        last_recovery_poll=time.monotonic()
                    if monitor.state['upstream_connected'] and ((dirty and complete) or monitor.state['fault']=='RECONNECT_RECONCILIATION_REQUIRED' or time.monotonic()-last_sync>=30):
                        client.reconcile()
                        last_sync=time.monotonic()
            except Exception as exc:
                monitor.invalidate('MONITOR_FAILURE_' + type(exc).__name__)
                print('PAPER_SAFETY_BLOCKED_' + type(exc).__name__,flush=True)
            finally:
                _close_owned_client(client,worker)
            if not stopped.is_set():
                stopped.wait((30,60,120,300)[min(attempts,3)])
                attempts+=1
        monitor.invalidate('MONITOR_STOPPED_RECONCILIATION_REQUIRED')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
