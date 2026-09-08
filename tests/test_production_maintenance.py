import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from trading.production_guard import instance_lock,validate_workspace
from trading.audit_writer import AuditWriter
from trading.ibkr_streaming import IbkrStreamingQuoteSource
from tests.test_ibkr_streaming import FakeStreamingClient


class MaintenanceTests(unittest.TestCase):
    def test_worktree_and_repo_state_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'code';root.mkdir();(root/'.git').write_text('gitdir: elsewhere')
            with self.assertRaisesRegex(RuntimeError,'worktrees'):validate_workspace(root,root,Path(tmp)/'state')
            (root/'.git').unlink();(root/'.git').mkdir()
            with self.assertRaisesRegex(RuntimeError,'outside'):validate_workspace(root,root,root/'state')
            validate_workspace(root,root,Path(tmp)/'state')

    def test_duplicate_instance_rejected_without_killing_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'service.lock'
            with instance_lock(path):
                with self.assertRaisesRegex(RuntimeError,'already running'):
                    with instance_lock(path):pass
            with instance_lock(path):pass

    def test_failed_audit_flush_keeps_pending_events(self):
        class Store:
            def append_many(self,events):raise OSError('disk full')
        writer=AuditWriter(Store());writer.submit('events',{'event_id':'e1'})
        with self.assertRaises(OSError):writer.flush()
        self.assertEqual(writer.queued_count,1)

    def test_streaming_start_is_idempotent_and_stop_joins(self):
        source=IbkrStreamingQuoteSource(symbols=['AAPL'],client_factory=FakeStreamingClient)
        self.assertTrue(source.start(.01));self.assertTrue(source.start(.01))
        self.assertEqual(len(source._client.requests),1)
        source.stop();self.assertIsNone(source._thread);self.assertFalse(source._client.connected)

    def test_streaming_timeout_releases_owner(self):
        def factory(mapping):
            client=FakeStreamingClient(mapping);client.ready.clear();return client
        source=IbkrStreamingQuoteSource(symbols=['AAPL'],client_factory=factory)
        self.assertFalse(source.start(.001));self.assertFalse(source._client.connected);self.assertIsNone(source._thread)

    def test_sqlite_fd_stays_flat_without_garbage_collection(self):
        # Isolated child with low limit makes the former connection leak fail deterministically.
        code=r'''
import gc,json,os,resource,subprocess,tempfile
from pathlib import Path
from trading.sqlite_event_store import SQLiteEventStore
from trading.paper_audit_db import insert_event
from trading.pool_state import PoolStateManager
soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE,(min(256,hard),hard))
gc.disable()
def fds():
 s=subprocess.run(['lsof','-nP','-a','-p',str(os.getpid()),'-Ff'],capture_output=True,text=True,check=True).stdout
 return sum(line.startswith('f') and line[1:].isdigit() for line in s.splitlines())
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'test.sqlite3';store=SQLiteEventStore(p);manager=PoolStateManager(db_path=p);samples=[fds()]
 for i in range(300):
  insert_event('canonical_pool_transition_events',{'transition_id':str(i)},db_path=p)
  store.append_many([('event_store',{'event_id':str(i)})]);manager.save();manager.load()
  if i%30==29:samples.append(fds())
 assert max(samples)-min(samples)<=2,samples
 print(json.dumps({'fd_samples':samples,'cycles':300,'gc_enabled':gc.isenabled()}))
'''
        p=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=90)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        result=json.loads(p.stdout);self.assertFalse(result['gc_enabled'])
        self.assertLessEqual(max(result['fd_samples'])-min(result['fd_samples']),2)
        print('FD regression:',json.dumps(result))

    def test_smoke_never_creates_missing_databases(self):
        from scripts import production_health
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.multiple(production_health,STATE_ROOT=root,AUDIT_DB=root/'audit.sqlite3',FINANCIAL_LEDGER=root/'finance.sqlite3',DELIVERY_LEDGER=root/'delivery.json'),patch.object(production_health,'process_inventory',return_value=[]):
                result=production_health.smoke()
            self.assertEqual(result['overall'],'NOT_READY');self.assertFalse((root/'audit.sqlite3').exists())

if __name__=='__main__':unittest.main()
