"""Synthetic journal reconciliation/restore; no production cursor or transport."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting import journal_rotation as journal
from reporting.journal_backup import backup_journal, inspect_backup, restore_journal
from reporting.journal_recovery import inspect_rotation, recover_rotation
from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator


def run_shadow(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    attempts=[0];before=len(os.listdir('/dev/fd'));threads=threading.active_count()
    def deny(*args,**kwargs):
        attempts[0]+=1
        raise PermissionError('Synthetic acceptance forbids network transport')
    with patch.object(socket.socket,'connect',deny),patch.object(socket.socket,'connect_ex',deny):
        outcomes={};source=directory/'source/history.jsonl'
        store=IncidentStore(directory/'shadow.sqlite3');reader=IncidentCollector(store)
        coordinator=RecoveryCoordinator(store.path)
        assert coordinator.begin_operation('TEST_ONLY_UNKNOWN','order',{})
        coordinator.finish_operation('TEST_ONLY_UNKNOWN','UNKNOWN')
        def event(key):
            return dict(timestamp='2026-10-27T10:00:00+00:00',local_plan_id=key,symbol='TEST_ONLY')
        journal.append_jsonl(source,event('baseline'));reader.rejections(source)
        journal.append_jsonl(source,event('unread'))
        opened=journal.os.open
        def fault(path,flags,*args,**kwargs):
            if Path(path)==source:raise OSError('Synthetic crash after rename')
            return opened(path,flags,*args,**kwargs)
        with patch.object(journal.os,'open',side_effect=fault):
            try:journal.rotate_journal(source)
            except OSError:pass
            else:raise AssertionError('Synthetic interruption did not occur')
        try:reader.rejections(source)
        except EvidenceChanged:pass
        else:raise AssertionError('Pending evidence was consumed')
        token=backup_journal(source,directory/'pending-backup')['approval_token']
        candidate=restore_journal(directory/'pending-backup',directory/'pending-restore',token)
        isolated=Path(candidate['journal']);plan=inspect_rotation(isolated)
        recover_rotation(isolated,plan['approval_token'])
        assert journal._paths(source)[2].exists()
        assert not candidate['cursor_updated'] and not candidate['production_activated']
        outcomes['pending_backup_restore_candidate_only']='PASS'
        plan=inspect_rotation(source);recover_rotation(source,plan['approval_token'])
        assert recover_rotation(source,plan['approval_token'])['status']=='ALREADY_COMPLETED'
        journal.append_jsonl(source,event('new'))
        assert reader.rejections(source,limit=1)==1
        assert IncidentCollector(IncidentStore(store.path)).rejections(source)==1
        assert reader.rejections(source)==0
        assert coordinator.uncertainties()==[('TEST_ONLY_UNKNOWN','order','UNKNOWN')]
        outcomes['reconcile_unread_tail_restart_no_replay']='PASS'
        outcomes['unknown_order_state_unchanged']='PASS'
        result=backup_journal(source,directory/'complete-backup')
        restored=restore_journal(directory/'complete-backup',directory/'complete-restore',result['approval_token'])
        active=Path(restored['journal']);journal.verify_active(active)
        assert active.read_bytes()==source.read_bytes() and journal.inode(active)!=journal.inode(source)
        for item in inspect_backup(directory/'complete-backup')['manifest']['files']:
            assert (directory/'complete-backup/payload'/item['path']).read_bytes()==(directory/'complete-restore/originals'/item['path']).read_bytes()
        outcomes['backup_hash_original_metadata_and_inode_map']='PASS'
        shutil.copytree(directory/'complete-backup',directory/'corrupt-backup')
        (directory/'corrupt-backup/payload/history.jsonl').write_text('TEST_ONLY altered evidence\n')
        try:restore_journal(directory/'corrupt-backup',directory/'refused-restore',result['approval_token'])
        except journal.JournalEvidenceError:pass
        else:raise AssertionError('Corruption accepted')
        assert not (directory/'refused-restore').exists()
        outcomes['corruption_refused_before_restore']='PASS'
        with closing(store.connect()) as c:
            assert c.execute('select count(*) from incident_events').fetchone()[0]==2
            integrity=c.execute('pragma integrity_check').fetchone()[0]
        assert integrity=='ok' and attempts[0]==0
        summary=dict(simulation_only=True,outcomes=outcomes,integrity=integrity,
            attempted_network_connections=attempts[0],fd_before=before,fd_after=len(os.listdir('/dev/fd')),
            threads_before=threads,threads_after=threading.active_count(),production_cursor_updated=False,
            production_state_activated=False,production_mail_enabled=False,trading_enabled=False)
        assert summary['fd_after']==before and summary['threads_after']==threads
        (directory/'summary.json').write_text(json.dumps(summary,indent=2))
        return summary


def main():
    from datetime import datetime,timezone
    from trading.production_paths import STATE_ROOT,maintenance_active
    from trading.production_guard import validate_workspace,instance_lock
    validate_workspace()
    if not (STATE_ROOT/'PAUSED').is_file() or not maintenance_active(STATE_ROOT):
        raise RuntimeError('Keep PAUSED and MAINTENANCE for isolated acceptance')
    if any((STATE_ROOT/'runtime'/name).exists() for name in ('EMAIL_ALERTS_ARMED','INCIDENT_COLLECTION_ARMED')):
        raise RuntimeError('Keep production collection and mail disarmed')
    parent=STATE_ROOT/'monitoring-tests';parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=parent/('journal-recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    with instance_lock(parent/'journal-recovery.lock'):
        print(json.dumps(run_shadow(target),sort_keys=True));print(str(target))


if __name__=='__main__':main()
