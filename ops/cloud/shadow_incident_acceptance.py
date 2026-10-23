"""Bounded synthetic shadow acceptance: isolated state and in-process fake SMTP."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.incident_mail import send_one
from reporting.journal_rotation import append_jsonl, rotate_journal
from reporting.recovery import RecoveryCoordinator


class FakeSMTP:
    """Never opens a socket; return values are simulation, never inbox proof."""
    def __init__(self, messages, fail=False):
        self.messages=messages; self.fail=fail
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def ehlo(self):pass
    def starttls(self,**kwargs):pass
    def login(self,*args):pass
    def send_message(self,message,**kwargs):
        self.messages.append(dict(subject=str(message['Subject']), simulation_only=True))
        if self.fail:raise TimeoutError('Synthetic lost ACK')
        return {}


def run_shadow(directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    now=[datetime.now(timezone.utc).timestamp()]
    fd_before=len(os.listdir('/dev/fd')); threads_before=threading.active_count()
    attempts=[0]
    original=socket.socket.connect; original_ex=socket.socket.connect_ex
    def deny(self,address):
        attempts[0]+=1
        raise PermissionError('Synthetic shadow has no network transport')
    socket.socket.connect=deny;socket.socket.connect_ex=deny
    try:
        outcomes={}
        # Persist unread old tail then follow a proven rotation without history replay.
        path=directory/'rejections.jsonl'; store=IncidentStore(directory/'rotation.sqlite3')
        collector=IncidentCollector(store)
        def rejected(key):return dict(timestamp='2026-10-23T15:00:00+00:00',local_plan_id=key,symbol='TEST_ONLY')
        append_jsonl(path,rejected('historical'));collector.rejections(path)
        append_jsonl(path,rejected('unread-old'));rotate_journal(path)
        append_jsonl(path,rejected('new'))
        assert collector.rejections(path,limit=1)==1
        assert IncidentCollector(IncidentStore(store.path)).rejections(path,limit=1)==1
        assert collector.rejections(path)==0
        with closing(store.connect()) as c:
            assert c.execute('SELECT COUNT(*) FROM incident_events').fetchone()[0]==2
        outcomes['rotation_tail_restart_no_replay']='PASS'
        # A missing receipt must fail closed without guessing an archive filename.
        path.rename(directory/'unregistered-old.jsonl');path.write_text('')
        try:collector.rejections(path)
        except EvidenceChanged:outcomes['unregistered_rotation_blocked']='PASS'
        else:raise AssertionError('Unproven rotation accepted')
        # Explicit protection evidence forms an alert/recovery chain through fake SMTP.
        db=directory/'protection.sqlite3'; coordinator=RecoveryCoordinator(db)
        store=IncidentStore(db,clock=lambda:now[0]); collector=IncidentCollector(store)
        path=directory/'protection.jsonl'; collector.protection_reports(path,'DUSHADOW1',guard=True)
        def protection(warning):
            return dict(timestamp=datetime.fromtimestamp(now[0],timezone.utc).isoformat(),source='position_guard',account='DUSHADOW1',
                protection_evidence_complete=not warning,symbols=[dict(symbol='TEST_ONLY',position_covered_by_stop=not warning,
                missing_stop_warning=warning,duplicate_stop_warning=False,underprotected_warning=False,overprotected_warning=False)])
        append_jsonl(path,protection(True));collector.protection_reports(path,'DUSHADOW1',guard=True)
        messages=[]; cfg=dict(host='relay.invalid',sender='shadow@example.invalid',username='fixture',relay_password='fixture')
        factory=lambda *args,**kwargs:FakeSMTP(messages)
        assert send_one(store,coordinator,cfg,trading_status='TEST_ONLY PAUSED',smtp_factory=factory)=='SMTP_ACCEPTED'
        now[0]+=1;append_jsonl(path,protection(False));collector.protection_reports(path,'DUSHADOW1',guard=True)
        assert send_one(store,coordinator,cfg,trading_status='TEST_ONLY PAUSED',smtp_factory=factory)=='SMTP_ACCEPTED'
        assert 'RECOVERY' in messages[-1]['subject'] and len(messages)==2
        outcomes['protection_alert_recovery_fake_transport']='PASS'
        # An ambiguous fake send blocks recovery across restart, never replaying DATA.
        db=directory/'uncertain.sqlite3';coordinator=RecoveryCoordinator(db);store=IncidentStore(db)
        store.ingest('shadow-failure','shadow-mail',dict(severity='RED',reason='TEST_ONLY'))
        store.ingest('shadow-recovery','shadow-mail',dict(severity='GREEN',reason='TEST_ONLY'),resolved=True)
        messages=[];factory=lambda *args,**kwargs:FakeSMTP(messages,fail=True)
        try:send_one(store,coordinator,cfg,smtp_factory=factory)
        except TimeoutError:pass
        else:raise AssertionError('Missing synthetic uncertain result')
        assert send_one(IncidentStore(db),RecoveryCoordinator(db),cfg,smtp_factory=factory)=='BLOCKED_UNKNOWN'
        assert len(messages)==1 and coordinator.uncertainties()[0][2]=='UNKNOWN'
        outcomes['smtp_unknown_restart_no_replay']='PASS'
        # Synthetic authentication/identity failure then fresh exact-account recovery.
        store=IncidentStore(directory/'runtime.sqlite3',clock=lambda:now[0]);collector=IncidentCollector(store)
        host=directory/'host.json';paper=directory/'paper.json'
        def snapshots(bad=False):
            stamp=datetime.fromtimestamp(now[0],timezone.utc).isoformat()
            host.write_text(json.dumps(dict(observed_at=stamp,services={'ibkr-api':'inactive'},service_details={'ibkr-api':{'unit_file_state':'disabled'}})))
            paper.write_text(json.dumps(dict(observed_at=stamp,source='REAL_IBKR',environment='PAPER',account_id='DUSHADOW2' if bad else 'DUSHADOW1',
                complete=not bad,resources={'connected_after_close':False})))
        snapshots();collector.runtime_snapshots(host,paper,'DUSHADOW1')
        now[0]+=1;snapshots(True);collector.runtime_snapshots(host,paper,'DUSHADOW1')
        alert=store.claim();assert alert['payload']['severity']=='RED';store.finish(alert['id'],'SMTP_ACCEPTED')
        now[0]+=1;snapshots();collector.runtime_snapshots(host,paper,'DUSHADOW1')
        assert store.claim()['kind']=='RECOVERY'
        outcomes['identity_and_expected_disabled_service']='PASS'
        integrity={}
        for db in directory.glob('*.sqlite3'):
            with closing(IncidentStore(db).connect()) as c:integrity[db.name]=c.execute('PRAGMA integrity_check').fetchone()[0]
        assert all(value=='ok' for value in integrity.values()) and attempts[0]==0
        summary=dict(simulation_only=True,transport='IN_PROCESS_FAKE_NO_NETWORK',outcomes=outcomes,integrity=integrity,
            attempted_network_connections=attempts[0],fd_before=fd_before,fd_after=len(os.listdir('/dev/fd')),
            threads_before=threads_before,threads_after=threading.active_count(),production_mail_enabled=False,trading_enabled=False)
        assert summary['fd_after']==fd_before and summary['threads_after']==threads_before
        (directory/'summary.json').write_text(json.dumps(summary,indent=2))
        return summary
    finally:
        socket.socket.connect=original;socket.socket.connect_ex=original_ex


def main():
    from trading.production_guard import validate_workspace, instance_lock
    from trading.production_paths import STATE_ROOT
    validate_workspace()
    if not (STATE_ROOT/'PAUSED').is_file() or not (STATE_ROOT/'runtime/MAINTENANCE').is_file():
        raise RuntimeError('This shadow acceptance requires PAUSED and MAINTENANCE')
    if any((STATE_ROOT/'runtime'/name).exists() for name in ('EMAIL_ALERTS_ARMED','INCIDENT_COLLECTION_ARMED')):
        raise RuntimeError('Disable production arming before shadow acceptance')
    os.umask(0o077)
    directory=STATE_ROOT/'monitoring-tests'/('rotation-fault-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    with instance_lock(STATE_ROOT/'monitoring-tests/rotation-fault.lock'):
        print(json.dumps(run_shadow(directory),sort_keys=True))
        print(str(directory))


if __name__=='__main__':main()
