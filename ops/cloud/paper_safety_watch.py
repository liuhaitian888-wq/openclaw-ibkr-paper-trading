"""Opt-in read-only continuous Paper order/protection monitor. No order transport."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime,timezone
import os
from pathlib import Path
import signal
import subprocess
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
from trading.signal_scheduler import strategy_dependency_registry



def attach_research_scanner(client, root):
    """Opt in on this already owned client; absent policy preserves monitoring."""
    policy_path=root/'runtime/screening-policy.json'
    if not policy_path.is_file():return None
    policy=json.loads(policy_path.read_text())
    if (policy.get('approved') is not True or policy.get('environment')!='PAPER'
            or policy.get('broker_scanner_readonly') is not True
            or policy.get('grants_trading_permission') is not False):return None
    from reporting.agent_secretary import SecretaryArchive
    from trading.broker_screening import BrokerScanner
    client.research_scanner=BrokerScanner(client,SecretaryArchive(root/'agent_secretary.sqlite3'))
    return client.research_scanner


def read_system_safety(root, manifest):
    """Bounded reads for existing global safety facts; never changes a gate."""
    safety=manifest.get('safety',{})
    result=dict(control_verified=safety.get('ownership_verified') is True,
        global_risk_verified=False,authoritative_state_verified=False,risk_isolatable=False,
        operator_paused=(root/'PAUSED').exists() or (root/'runtime/MAINTENANCE').exists())
    try:
        with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
            c.execute('PRAGMA query_only=ON')
            rows={k:json.loads(v) for k,v in c.execute("SELECT name,payload FROM module_observations WHERE name IN ('RISK','CANONICAL_STATE')")}
            uncertain=bool(c.execute("SELECT 1 FROM operation_attempts WHERE kind='order' AND status IN ('STARTED','UNKNOWN') LIMIT 1").fetchone())
        def verified(name):
            row=rows.get(name,{})
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['observed_at'])).total_seconds()
            return row.get('state')=='HEALTHY' and row.get('freshness')=='FRESH' and 0<=age<=120
        result.update(global_risk_verified=safety.get('risk_allowed') is True and verified('RISK'),
            authoritative_state_verified=manifest.get('canonical_current_state_verified') is True and verified('CANONICAL_STATE'),
            risk_isolatable=safety.get('risk_isolatable') is True and not uncertain)
        config=root.parents[2]/'.config/openclaw/paper.env'
        values=dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line and not line.startswith('#'))
        result['operator_paused']=result['operator_paused'] or values.get('TRADING_KILL_SWITCH','true').lower()!='false' or values.get('ALLOW_PAPER_TRANSMIT','false').lower()!='true'
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        result.update(control_verified=False,global_risk_verified=False,authoritative_state_verified=False,risk_isolatable=False)
    return result


def gateway_generation():
    """Read-only local process evidence; never start/restart the Gateway."""
    try:
        pid=int(subprocess.check_output(['systemctl','show','ibkr-gateway.service','-p','MainPID','--value'],timeout=2,text=True))
        if pid<=0:return None
        return gateway_process_generation(Path('/proc'),pid)
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):return None


def gateway_process_generation(proc, owner_pid):
    """Identify the owned Gateway Java child beneath the persistent automater.

    Walk only this owner's process tree, not unrelated Java peers. Fail closed
    if the child is absent/ambiguous; the Python/.NET owner is not a session.
    """
    pending=[owner_pid];seen=set();gateways=[]
    while pending and len(seen)<32:
        pid=pending.pop()
        if pid in seen:continue
        seen.add(pid)
        try:
            base=proc/str(pid)
            executable=(base/'comm').read_text().strip()
            command=(base/'cmdline').read_bytes().replace(b'\0',b' ')
            if executable=='java' and (b'ibgateway' in command.lower() or b'ibcalpha' in command.lower()):
                start=(base/'stat').read_text().rsplit(')',1)[1].split()[19]
                gateways.append(str(pid)+':'+start)
            children=(base/'task'/str(pid)/'children').read_text().split()
            pending.extend(int(child) for child in children)
        except (OSError,ValueError,IndexError):
            continue
    return gateways[0] if len(gateways)==1 and not pending else None


def api_listener_ready():
    """Passive Linux kernel evidence only; no connect, subscription or login."""
    readable=False
    # Java commonly publishes a dual-stack wildcard listener in tcp6. This is
    # readiness evidence only, never a bind/firewall change or identity proof.
    tables=(('/proc/net/tcp',{'0100007F','00000000'}),
            ('/proc/net/tcp6',{'00000000000000000000000000000000','0000000000000000FFFF00000100007F'}))
    for name,addresses in tables:
        try:rows=Path(name).read_text().splitlines()[1:];readable=True
        except OSError:continue
        for line in rows:
            parts=line.split()
            if len(parts)>3 and parts[3]=='0A' and parts[1].upper() in {address+':0FA2' for address in addresses}:return True
    return False if readable else None


def api_heartbeat_fresh(state, now):
    """TCP being open and IBKR upstream being down don't prove API liveness."""
    stamp=state.get('last_server_reply')
    return type(stamp) in (int,float) and 0<=now-stamp<=10


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    config_path=Path.home()/'.config/openclaw/paper-safety.json'
    if config_path.stat().st_mode & 0o077:
        raise PermissionError('Private monitor configuration must be 0600')
    cfg=json.loads(config_path.read_text())
    if cfg.get('bar_wire_protocol','auto') not in ('auto','legacy'):
        raise PermissionError('Unsupported read-only bar wire protocol')
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
        limits=manifest.get('execution_limits',{})
        observer=PaperStrategyObserver(cfg['symbols'],strategy,root/'reports/paper_strategy/latest.json',
            max_quantity=limits.get('max_quantity',1),max_order_value=limits.get('max_order_value',200),max_risk=limits.get('max_risk_per_order',10),
            signal_configurations=manifest.get('signal_strategy_configurations'))
        dependencies=strategy_dependency_registry(manifest.get('signal_strategy_configurations'),cfg['symbols'])
        safety=manifest.get('safety',{})
        safety_cache={'at':0,'value':{}}
        def current_system_safety():
            if time.monotonic()-safety_cache['at']>=1:
                safety_cache.update(at=time.monotonic(),value=read_system_safety(root,manifest))
            return safety_cache['value']
        monitor=PaperSafetyMonitor(root/'trading_audit.sqlite3',root/'runtime/recovery.sqlite3',
            symbols=cfg['symbols'],required_bars=strategy['slow_window'],strategy_dependencies=dependencies,
            system_safety_provider=current_system_safety,
            system_safety={'control_verified':safety.get('ownership_verified') is True,  # execution ownership is separate from held monitor lock
                'global_risk_verified':safety.get('risk_allowed') is True,
                'authoritative_state_verified':manifest.get('canonical_current_state_verified') is True,
                'risk_isolatable':safety.get('risk_isolatable') is True,
                'operator_paused':(root/'PAUSED').exists() or (root/'runtime/MAINTENANCE').exists()})
        monitoring=json.loads((root/'runtime/monitoring-deployment.json').read_text())
        cashbook_publisher=None
        if monitoring.get('native_cashbook_observation_approved') is True:
            from trading.native_cash_publication import publish_native_cashbook
            cashbook_publisher=lambda book:publish_native_cashbook(root,monitor,book)
        else:
            monitor.coordinator.observe('CURRENCY_BOOK','PAUSED',freshness='UNKNOWN',enabled=False,
                reason='Continuous native cash observation not configured',grants_trading_permission=False)
        from trading.native_health_bridge import NativeOwnerHealthBridge,disable_native_health_owner
        native_health=None
        if monitoring.get('native_account_health_observation_approved') is True:
            if cashbook_publisher is None:raise PermissionError('Native account health requires the approved native ledger owner')
            native_health=NativeOwnerHealthBridge(root,monitor)
        else:disable_native_health_owner(monitor.coordinator)
        from trading.paper_readonly_resume import claim_resume,confirm_resume,retain_failed_resume
        while not stopped.is_set():
            explicit_resume=None
            generation=gateway_generation();listening=api_listener_ready()
            admitted=False if monitor.persistence_circuit.blocked else monitor.admit_connection(generation,api_listening=listening)
            resume_candidate=None
            if not admitted:
                try:resume_candidate=claim_resume(monitor,root,monitoring,generation,api_listening=listening,claim=False)
                except sqlite3.Error as exc:monitor.persistence_circuit.block(exc,'readonly_resume_claim')
                if resume_candidate is None:
                    if not monitor.persistence_circuit.blocked:
                        try:monitor.invalidate('CONNECTION_BUDGET_OR_BACKOFF; independent readback continues')
                        except sqlite3.Error as exc:monitor.persistence_circuit.block(exc,'connection_wait_publication')
                    stopped.wait(30)
                    continue
            client=None;worker=None
            try:
                client=PaperSafetyClient(monitor,cfg['symbols'],bar_wire_protocol=cfg.get('bar_wire_protocol','auto'),cashbook_publisher=cashbook_publisher,native_pnl_observation=monitoring.get('native_account_health_observation_approved') is True)
                client.strategy_observer=observer
                attach_research_scanner(client,root)
                secretary_policy=root/'runtime/secretary-policy.json'
                if secretary_policy.is_file() and json.loads(secretary_policy.read_text()).get('broker_queries_approved') is True:
                    from trading.secretary_broker_owner import SecretaryBrokerOwner
                    from reporting.agent_secretary import SecretaryArchive
                    client.secretary_broker=SecretaryBrokerOwner(client,SecretaryArchive(root/'agent_secretary.sqlite3'))
                if not admitted:
                    explicit_resume=claim_resume(monitor,root,monitoring,gateway_generation(),api_listening=api_listener_ready())
                    if explicit_resume is None:raise RuntimeError('Explicit readonly recovery scope no longer admissible')
                if explicit_resume is not None:explicit_resume['transport_started']=True
                client.connect('127.0.0.1',4002,clientId=18770)
                worker=threading.Thread(target=client.run_loop,name='paper-safety-api',daemon=True)
                worker.start()
                if not client.ready.wait(10) or not client.accounts_ready.wait(10):
                    monitor.invalidate('AUTHENTICATION_OR_CONNECTION_REQUIRED')
                    raise RuntimeError('Human authentication or connection review required')
                with monitor.lock:
                    monitor.begin(client.accounts,upstream_reported_lost=client.upstream_reported_lost)
                client.reconcile()
                initial_subscription_due=True
                connected_since=monitor.clock()
                last_sync=time.monotonic()
                last_heartbeat=0
                last_strategy=0
                last_recovery_poll=0
                while not stopped.wait(1):
                    try:
                        if not worker.is_alive() or not client.isConnected() or not monitor.state['connected']:
                            raise RuntimeError('Order monitoring connection lost')
                        if time.monotonic()-last_heartbeat>=5:
                            client.reqCurrentTime()
                            last_heartbeat=time.monotonic()
                        if not api_heartbeat_fresh(monitor.state,monitor.clock()):
                            raise RuntimeError('Broker callback heartbeat missing')
                        if monitor.persistence_circuit.blocked:
                            monitor.persistence_circuit.poll(client)
                            if native_health is not None:native_health.invalidate('Local snapshot journal requires verified reconciliation')
                            continue
                        if initial_subscription_due:
                            client.subscribe()
                            initial_subscription_due=False
                        with monitor.lock:
                            monitor._publish()
                            dirty=monitor.state['dirty']
                            complete=set(monitor.state['ends'])==ENDS
                        if monitor.persistence_circuit.blocked:continue
                        if explicit_resume is None:monitor.validate_connection(connected_since,connection_generation=client.connection_generation)
                        else:confirm_resume(monitor,explicit_resume,connected_since,gateway_generation())
                        if monitor.persistence_circuit.blocked:continue
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
                        if client.research_scanner is not None:
                            with monitor.lock:
                                scan_state=dict(monitor.state)
                            scanner_admitted=(scan_state.get('identity') is True and scan_state.get('upstream_connected') is True
                                              and scan_state.get('connected') is True and not scan_state.get('dirty',True)
                                              and set(scan_state.get('ends',[]))==ENDS and 0<=monitor.clock()-scan_state.get('last_server_reply',0)<=10)
                            client.research_scanner.poll(admitted=scanner_admitted)
                        # Keep monitoring during 10197. Only bounded data subscription
                        # retries; no Gateway process action, no account session takeover.
                        if time.monotonic()-last_recovery_poll>=5:
                            if monitor.state['upstream_connected']:client.retry_pending_initial()
                            client.backfill_history_gaps()
                            for action in monitor.poll_symbol_recovery():
                                client.retry_symbol_subscriptions(action['symbols'],bars_only=action['action']=='RESUBSCRIBE_BARS',
                                    low_frequency=action.get('low_frequency',False))
                            last_recovery_poll=time.monotonic()
                        if client.secretary_broker is not None and client.secretary_broker.poll():
                            last_sync=time.monotonic()
                        if native_health is not None:native_health.poll()
                        if monitor.state['upstream_connected'] and ((dirty and complete) or monitor.state['fault']=='RECONNECT_RECONCILIATION_REQUIRED' or time.monotonic()-last_sync>=30):
                            client.reconcile()
                            last_sync=time.monotonic()
                        client.poll_cashbook()
                        client.poll_pnl()
                    except sqlite3.Error as exc:
                        monitor.persistence_circuit.block(exc,'owned_monitor_loop')
            except sqlite3.Error as exc:
                monitor.persistence_circuit.block(exc,'local_client_preparation')
                stopped.wait(5)
            except Exception as exc:
                if native_health is not None:native_health.invalidate('Owned SDK readback unavailable: '+type(exc).__name__)
                try:monitor.invalidate('MONITOR_FAILURE_' + type(exc).__name__)
                except sqlite3.Error as store_error:monitor.persistence_circuit.block(store_error,'owner_failure_publication')
                from reporting.errors import redact
                print(json.dumps({'state':'PAPER_SAFETY_BLOCKED','error_type':type(exc).__name__,
                    'message':redact(str(exc)[:400])}),flush=True)
            finally:
                try:
                    retain_failed_resume(monitor,explicit_resume)
                except sqlite3.Error as exc:monitor.persistence_circuit.block(exc,'readonly_resume_outcome')
                if client is not None:
                    try:
                        try:
                            if client.secretary_broker is not None:client.secretary_broker.close()
                        finally:
                            if client.research_scanner is not None:client.research_scanner.close()
                    finally:
                        try:client.close_cashbook()
                        finally:
                            try:client.close_pnl()
                            finally:_close_owned_client(client,worker)
        if native_health is not None:native_health.close()
        monitor.invalidate('MONITOR_STOPPED_RECONCILIATION_REQUIRED')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
