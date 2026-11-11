from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.link_status_card import snapshot, authorize, queue, valid, render, SOURCE_THREAD, SOURCE_MESSAGE
from reporting.notification_center import get_item
from test_publication_policy import CONFIG

class NativeRegistryCardTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.now=1000
        self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)
        self.co=RecoveryCoordinator(self.store.path)
        self.p=dict(connected=True,identity=True,upstream_connected=True,dirty=False,epoch='epoch-A',reset_at=900,
                    ends=['completed_orders','executions','orders','positions'],last_server_reply=self.now,reconciled_at=self.now)
        self.sample=dict(account='DUQ503649',environment='PAPER',observed_at=self.now,api_connected=True,
                         identity_verified=True,upstream_connected=True,server_reply_at=self.now,reconciliation_complete=True)
        with closing(self.store.connect()) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('CREATE TABLE paper_health_samples(epoch TEXT,minute_bucket INTEGER,observed REAL,payload TEXT,PRIMARY KEY(epoch,minute_bucket))')
            obs={'NATIVE_BROKER_SESSION':dict(enabled=False,state='PAUSED',freshness='UNKNOWN',reason='PRIVATE RAW REASON'),
                 'ACCOUNT':dict(account='DUQ503649',environment='PAPER',state='DEGRADED',freshness='STALE',reason='PRIVATE RAW REASON')}
            c.executemany('INSERT INTO module_observations VALUES(?,?)',[(k,json.dumps(v)) for k,v in obs.items()])
        self.persist()
        guard=patch('reporting.automatic_notifications.persistence_clear',return_value=True);guard.start();self.addCleanup(guard.stop)
        (self.root/'PAUSED').touch()
    def persist(self,epoch=None):
        with closing(self.store.connect()) as c,c:
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES(1,?)',(json.dumps(self.p),))
            c.execute('INSERT OR REPLACE INTO paper_health_samples VALUES(?,?,?,?)',(epoch or self.p['epoch'],int(self.sample['observed_at']//60),self.sample['observed_at'],json.dumps(self.sample)))
    def view(self):return snapshot(self.store,self.root,self.now)
    def observer(self,**changes):
        value=dict(source='REAL_IBKR',environment='PAPER',account_id='DUQ503649',account_fingerprint=hashlib.sha256(b'DUQ503649').hexdigest(),complete=True,status='READBACK_COMPLETE',
            observed_at=datetime.fromtimestamp(self.now,timezone.utc).isoformat(),gateway_api_handshake=True,server_time=self.now,
            end_markers=['summary','orders','positions','executions'],positions=[],orders=[],executions=[],resources=dict(connected_after_close=False,reader_stopped=True,worker_stopped=True))
        value.update(changes);(self.root/'runtime/paper-observer.latest.json').write_text(json.dumps(value));return value
    def test_native_recovery_is_separate_from_disabled_registration_and_gates(self):
        s=self.view();self.assertIn('已核验',s['account']);self.assertIn('原生登记未启用',s['registry']);self.assertIn('账户登记陈旧',s['registry']);self.assertEqual(s['gates'],'暂停/维护中')
        self.assertNotIn('PRIVATE',str(s));self.assertNotIn('DUQ',str(s))
    def test_stale_reconciliation_is_history_not_current_ready_or_disconnected(self):
        self.p['reconciled_at']=self.now-31;self.persist();s=self.view()
        self.assertIn('本会话曾完整回读',s['account']);self.assertNotIn('已核验',s['account']);self.assertIn('近期API回执',s['tcp'])
    def test_wrong_account_environment_epoch_or_stale_sample_never_green(self):
        for field,value in [('account','DU_OTHER'),('environment','LIVE'),('reconciliation_complete',False),('observed_at',self.now-91)]:
            with self.subTest(field=field):
                original=self.sample.copy();self.sample[field]=value
                with closing(self.store.connect()) as c,c:c.execute('DELETE FROM paper_health_samples')
                self.persist();self.assertNotIn('已核验',self.view()['account']);self.sample=original
        self.persist();self.p['epoch']='epoch-B'
        with closing(self.store.connect()) as c,c:c.execute('UPDATE paper_safety_state SET payload=?',(json.dumps(self.p),))
        self.assertNotIn('已核验',self.view()['account'])
    def test_heartbeat_does_not_refresh_account_proof(self):
        self.sample['observed_at']=self.now-100;self.sample['server_reply_at']=self.now-100
        self.p['reconciled_at']=self.now-100;self.persist()
        self.assertNotIn('已核验',self.view()['account'])
    def test_disconnect_dirty_or_persistence_fault_never_claims_current_recovery(self):
        for field,value in [('connected',False),('identity',False),('upstream_connected',False),('dirty',True)]:
            with self.subTest(field=field):
                old=self.p[field];self.p[field]=value;self.persist();self.assertNotIn('已核验',self.view()['account']);self.p[field]=old
        self.persist()
        with patch('reporting.automatic_notifications.persistence_clear',return_value=False):
            self.assertNotIn('已核验',self.view()['account']);self.assertIn('持久性',self.view()['account'])
    def test_independent_closed_exact_readback_never_substitutes_primary_epoch(self):
        self.observer();self.p['connected']=False;self.persist();s=self.view()
        self.assertIn('完整快照已核验',s['readback']);self.assertIn('不替代常驻会话',s['readback']);self.assertNotIn('已核验',s['account'])
    def test_independent_readback_rejects_wrong_scope_incomplete_open_or_old(self):
        for changes in [dict(source='MOCK'),dict(account_id='DU_OTHER'),dict(environment='LIVE'),dict(complete=False),dict(end_markers=['summary']),dict(resources=dict(connected_after_close=True,reader_stopped=True,worker_stopped=True)),dict(orders=[{'account':'DU_OTHER'}]),dict(account_fingerprint='bad'),dict(broker_epoch='old-epoch')]:
            with self.subTest(changes=changes):
                self.observer(**changes);self.assertNotIn('已核验',self.view()['readback'])
        self.observer();self.now+=601;self.assertIn('过期',self.view()['readback'])
    def test_observer_before_reset_future_or_naive_is_not_current(self):
        for at in [self.now-601,self.now+1]:
            self.observer(observed_at=datetime.fromtimestamp(at,timezone.utc).isoformat(),server_time=at);self.assertNotIn('已核验',self.view()['readback'])
        self.observer();self.p['reset_at']=self.now+1;self.persist();self.assertIn('上轮',self.view()['readback'])
        self.observer(observed_at='2026-11-11T06:13:42');self.assertNotIn('已核验',self.view()['readback'])
    def test_new_epoch_after_queue_invalidates_old_current_card(self):
        authorize(self.store,CONFIG,source_thread=SOURCE_THREAD,source_message=SOURCE_MESSAGE);queue(self.store,self.root,CONFIG);item=get_item(self.store,1)
        self.assertTrue(valid(self.store,item,CONFIG));self.p['epoch']='epoch-B';self.p['identity']=False;self.persist();self.assertFalse(valid(self.store,item,CONFIG))
    def test_fixed_render_is_bounded_safe_and_old_versions_remain_readable(self):
        self.observer();s=self.view();text=render(dict(payload=dict(links=s,observed_at=self.now)))
        self.assertIn('独立回读',text);self.assertIn('健康登记',text);self.assertNotIn('PRIVATE',text);self.assertNotIn('DUQ503649',text)
        self.assertLess(len(text),1500);s.pop('registry');s.pop('readback');self.assertIn('旧版快照',render(dict(payload=dict(links=s,observed_at=self.now))))
