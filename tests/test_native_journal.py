"""Trusted local protocol fixtures only: no Codex binary, OAuth or network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reporting.codex_appserver import run
from reporting.native_journal import (NativeJournal, NativeDeadlineExceeded,
    NativeStderrBudgetExceeded, JournalWriteError)


class NativeJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.home = self.root/'oauth'; self.home.mkdir()
        self.empty = self.root/'empty'; self.empty.mkdir()
        self.path = self.root/'artifacts/native-journal.json'
        self.children = []; self.records = []
        original = subprocess.Popen
        def child(*args, **kwargs):
            process = original(*args, **kwargs); self.children.append(process); return process
        self.p = patch('reporting.codex_appserver.subprocess.Popen', side_effect=child)
        self.p.start(); self.addCleanup(self.p.stop)
        self.p = patch('reporting.codex_appserver.preflight')
        self.p.start(); self.addCleanup(self.p.stop)

    def fake(self, mode):
        path = self.root/'fixture'
        path.write_text('''#!/usr/bin/env python3
import json,os,sys,time,signal
MODE=''' + repr(mode) + '''
def send(x):print(json.dumps(x),flush=True)
for line in sys.stdin:
 m=json.loads(line);method=m['method'];i=m.get('id')
 if method=='initialize':send({'id':i,'result':{}})
 elif method=='thread/start':send({'id':i,'result':{'thread':{'id':'thread'},'model':'gpt-6.1-sol','modelProvider':'secretary_oauth','approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}})
 elif method=='turn/start':
  send({'id':i,'result':{'turn':{'id':'turn','status':'inProgress'}}})
  if MODE=='crash':os._exit(17)
  if MODE=='stderr':sys.stderr.write('private_stderr_'+'x'*1000001);sys.stderr.flush();time.sleep(30)
  if MODE=='silent':time.sleep(30)
  if MODE=='partial':sys.stdout.write('private_partial');sys.stdout.flush();time.sleep(30)
  if MODE=='malformed':print('private_malformed{',flush=True);time.sleep(30)
  if MODE=='kill':signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)
  if MODE=='many':
   for j in range(80):send({'method':'item/completed','params':{'threadId':'thread','turnId':'turn','item':{'id':'reason-'+str(j),'type':'reasoning','text':'private_reasoning'}}})
  send({'method':'item/completed','params':{'threadId':'thread','turnId':'turn','item':{'id':'answer','type':'agentMessage','text':json.dumps({'unexpected':'private_schema'} if MODE=='schema' else {'summary':'public result'})}}})
  send({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}})
''')
        path.chmod(0o700); return path

    def invoke(self, mode='complete'):
        def record(stage, value):
            self.records.append((stage, value))
            if stage == 'TURN_COMPLETED':
                (self.root/'public-completion.json').write_text(json.dumps(value))
        return run({'prompt':'private_input'}, home=self.home, empty_dir=self.empty,
            record=record, codex=self.fake(mode), timeout=1, journal_path=self.path)

    def read(self):
        return json.loads(self.path.read_text())

    def closed(self):
        self.assertEqual(1, len(self.children))
        child = self.children[0]
        self.assertIsNotNone(child.poll()); self.assertTrue(child.stdin.closed); self.assertTrue(child.stdout.closed)

    def test_completion_checkpoint_is_durable_and_journal_has_no_content(self):
        result = self.invoke('many'); self.closed(); data = self.read()
        self.assertEqual(result, json.loads((self.root/'public-completion.json').read_text()))
        self.assertTrue(data['acceptance_observed']); self.assertTrue(data['completion_checkpointed'])
        self.assertEqual('NATIVE_COMPLETION_CHECKPOINTED', data['outcome'])
        self.assertEqual(80, data['items']['reasoning:completed'])
        self.assertEqual(16, len(data['item_tail'])); self.assertEqual('answer', data['item_tail'][-1]['item_id'])
        self.assertLess(self.path.stat().st_size, NativeJournal.MAX_BYTES)
        self.assertEqual(0, self.path.stat().st_mode & 0o077)
        for secret in ('private_input','private_reasoning','public result','auth.json','CODEX_HOME'):
            self.assertNotIn(secret, self.path.read_text())
        self.assertGreater(data['stdout_bytes'],0); self.assertGreater(data['stdin_bytes'],0)
        self.assertEqual(1, data['effective_timeout_seconds'])
        self.assertEqual(1, data['deadline_monotonic']-data['started_monotonic'])

    def test_native_deadline_is_separate_from_stderr_budget(self):
        with self.assertRaises(NativeDeadlineExceeded):self.invoke('silent')
        self.closed(); data = self.read()
        self.assertEqual('NATIVE_DEADLINE', data['failure_code']); self.assertTrue(data['acceptance_observed'])
        self.assertEqual('UNKNOWN', data['outcome']); self.assertEqual(0,data['stderr_bytes'])
        self.assertTrue(data['cleanup']['pipes_closed']); self.assertFalse(data['completion_checkpointed'])

    def test_stderr_limit_does_not_become_deadline_or_record_raw_stderr(self):
        with self.assertRaises(NativeStderrBudgetExceeded):self.invoke('stderr')
        self.closed(); data = self.read()
        self.assertEqual('STDERR_BUDGET', data['failure_code']); self.assertGreater(data['stderr_bytes'],1000000)
        self.assertNotIn('private_stderr', self.path.read_text()); self.assertEqual('UNKNOWN',data['outcome'])

    def test_partial_line_is_counted_without_logging_it(self):
        with self.assertRaises(NativeDeadlineExceeded):self.invoke('partial')
        self.closed();self.assertEqual(len('private_partial'), self.read()['partial_line_bytes'])
        self.assertNotIn('private_partial',self.path.read_text())

    def test_malformed_rpc_cleans_up_and_records_only_error_type(self):
        with self.assertRaises(json.JSONDecodeError):self.invoke('malformed')
        self.closed();self.assertEqual('JSONDecodeError',self.read()['error_type'])
        self.assertNotIn('private_malformed',self.path.read_text());self.assertFalse(self.read()['completion_checkpointed'])

    def test_bad_public_schema_never_records_completion(self):
        with self.assertRaises(ValueError):self.invoke('schema')
        self.closed();self.assertEqual('UNKNOWN',self.read()['outcome'])
        self.assertFalse(self.read()['completion_checkpointed']);self.assertFalse((self.root/'public-completion.json').exists())
        self.assertNotIn('private_schema',self.path.read_text())

    def test_child_crash_records_exit_code_without_relaunch(self):
        with self.assertRaises(RuntimeError):self.invoke('crash')
        self.closed();self.assertEqual(17,self.read()['cleanup']['child_exit_code'])
        self.assertEqual('UNKNOWN',self.read()['outcome'])

    def test_term_ignored_uses_bounded_kill_of_owned_child(self):
        with self.assertRaises(NativeDeadlineExceeded):self.invoke('kill')
        self.closed();self.assertTrue(self.read()['cleanup']['term_requested'])
        self.assertTrue(self.read()['cleanup']['kill_requested'])

    def test_initial_journal_failure_prevents_child(self):
        with patch.object(NativeJournal,'_write',side_effect=OSError('fabricated disk error')):
            with self.assertRaises(JournalWriteError):self.invoke()
        self.assertEqual([],self.children)

    def failing_write(self, phase):
        original=NativeJournal._write
        def write(journal,exclusive):
            if journal.state['phase']==phase:raise OSError('fabricated journal failure')
            return original(journal,exclusive)
        return patch.object(NativeJournal,'_write',write)

    def test_journal_failure_after_native_acceptance_is_fail_closed_and_cleans_up(self):
        with self.failing_write('TURN_ACCEPTED'):
            with self.assertRaises(JournalWriteError):self.invoke('silent')
        self.closed();self.assertNotIn('TURN_COMPLETED',[x[0] for x in self.records])

    def test_completed_checkpoint_survives_journal_projection_failure(self):
        with self.failing_write('TURN_COMPLETED'):
            with self.assertRaises(JournalWriteError):self.invoke()
        self.closed();self.assertEqual('TURN_COMPLETED',self.records[-1][0])
        self.assertEqual('public result',json.loads((self.root/'public-completion.json').read_text())['summary'])

    def test_existing_or_symlink_journal_cannot_be_overwritten(self):
        self.path.parent.mkdir(); self.path.write_text('retained')
        with self.assertRaises(JournalWriteError):self.invoke()
        self.assertEqual('retained',self.path.read_text());self.assertEqual([],self.children)
        self.path.unlink(); self.path.symlink_to(self.root/'outside')
        with self.assertRaises(JournalWriteError):self.invoke()
        self.assertFalse((self.root/'outside').exists());self.assertEqual([],self.children)
