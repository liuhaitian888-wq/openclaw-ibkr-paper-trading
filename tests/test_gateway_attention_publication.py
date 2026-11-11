import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading.gateway_readiness import observe, publish, KIND
from trading.gateway_recovery import decide, ACCOUNT, ENDS
from ops.cloud.gateway_watchdog import operator_observation
from ops.cloud import gateway_watchdog as watchdog
from reporting.gateway_session_events import collect, phase
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.publication_policy import prepare, decision, validate
from reporting.notification_center import get_item, render
from reporting.incident_telegram import send_one
from reporting.link_status_card import snapshot, render as render_card
from test_publication_policy import CONFIG
import test_notification_center as fixtures


class GatewayAttentionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.now=1000
        self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)
        self.co=RecoveryCoordinator(self.store.path,clock=lambda:self.now)
        prepare(self.store,CONFIG)
        self.native(False)

    def native(self, ready):
        p=dict(connected=ready,identity=ready,upstream_connected=ready,dirty=not ready,
               ends=list(ENDS) if ready else [],last_server_reply=self.now if ready else 0)
        with closing(self.store.connect()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES(1,?)',(json.dumps(p),))
        return p

    def evidence(self, now, ready=False):
        return dict(approved=True,generation='1:100',generation_started_at=900,service='active',
                    native=dict(connected=ready,identity=ready,upstream_connected=ready,dirty=not ready,
                                ends=list(ENDS) if ready else [],last_server_reply=now if ready else 0),
                    readback=dict(complete=ready,account_id=ACCOUNT,environment='PAPER',at=now,
                                  server_time=now if ready else 0,gateway_api_handshake=True))

    def open(self):
        state=dict(operation='RECOVERED',request_id='original',last_attempt=100)
        for now in range(1000,1901,30):
            state,action=decide(state,self.evidence(now),now)
            self.assertEqual(action,'NONE')
            state=observe(state,self.evidence(now),now)
        self.now=1900
        self.assertTrue(state['readiness_requires_operator'])
        return state

    def persist(self, state):
        (self.root/'runtime/gateway-recovery-state.json').write_text(json.dumps(state))

    def notice(self):
        with closing(self.store.connect()) as c:
            row=c.execute('SELECT id FROM notification_outbox WHERE kind=? ORDER BY id DESC LIMIT 1',(KIND,)).fetchone()
        return get_item(self.store,row[0]) if row else None

    def stage(self):
        s=self.open();self.persist(s);publish(self.store,s);prepare(self.store,CONFIG)
        return s,self.notice()

    def send(self,bot):
        return asyncio.run(send_one(self.store,self.co,CONFIG,report_root=self.root,owned_bot=bot,clock=lambda:self.now))

    def test_business_dead_protocol_alive_preserves_restart_budget_and_op(self):
        s=self.open()
        self.assertEqual((s['operation'],s['request_id'],s['last_attempt']),('RECOVERED','original',100))
        self.assertEqual(s['readiness_episode']['cause'],'BUSINESS_READINESS_UNVERIFIED')

    def test_missing_stale_duplicate_generation_or_poll_gap_never_confirms(self):
        for variant in ('stale','same','missing','generation','gap'):
            s={}
            for now in range(1000,1901,30):
                e=self.evidence(now)
                if variant=='stale':e['readback']['at']=0
                if variant=='same':e['readback']['at']=1000
                if variant=='missing':e['readback'].pop('gateway_api_handshake')
                if variant=='generation':e['generation']=str(now)
                if variant=='gap' and now in (1300,1330,1360,1390):continue
                s=observe(s,e,now)
            self.assertNotIn('readiness_episode',s,variant)

    def test_independent_probe_failure_does_not_mislabel_healthy_primary_as_dead(self):
        s={}
        for now in range(1000,2801,30):
            e=self.evidence(now,True);e['readback']['complete']=False
            s=observe(s,e,now)
        self.assertNotIn('readiness_episode',s);self.assertFalse(s['readiness_requires_operator'])

    def test_exact_identity_mismatch_still_requires_action_when_primary_disagrees(self):
        self.now=1900;e=self.evidence(self.now,True)
        e.update(identity_mismatch=True);e['readback'].update(complete=False,account_id='OTHER')
        s=observe({},e,self.now);self.persist(s);publish(self.store,s);self.native(True)
        item=self.notice();self.assertEqual(item['payload']['cause'],'IDENTITY_UNVERIFIED')
        self.assertTrue(validate(self.store,item,CONFIG))

    def test_source_registration_one_private_wire_and_no_group_mirror(self):
        s,item=self.stage()
        self.assertTrue(validate(self.store,item,CONFIG))
        view=render(item,CONFIG,self.now)
        self.assertEqual(view['audience'],'owner');self.assertIn('人工检查',view['text'])
        for forbidden in ('DUQ503649','原始错误','episode_id'):self.assertNotIn(forbidden,view['text'])
        bot=fixtures.NotificationCenterTests.bot(self)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual([x[0] for x in bot.sends],[42])
        publish(self.store,s);publish(self.store,s)
        self.assertEqual(self.send(bot),'EMPTY');self.assertEqual(len(bot.sends),1)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('select count(*) from notification_outbox where kind=?',(KIND,)).fetchone()[0],1)

    def test_required_gateway_action_has_mandatory_delivery_priority(self):
        from reporting.notification_center import critical
        _,item=self.stage();self.assertTrue(critical(item))

    def test_unknown_never_replays_or_creates_another_notice(self):
        s,item=self.stage()
        claimed=self.store.claim(publication_config=CONFIG);self.assertEqual(claimed['id'],item['id'])
        self.store.finish(item['id'],'UNKNOWN')
        self.now+=1800;s['readiness_checked_at']=self.now;self.persist(s);publish(self.store,s)
        bot=fixtures.NotificationCenterTests.bot(self);self.assertEqual(self.send(bot),'BLOCKED_UNKNOWN');self.assertEqual(bot.sends,[])
        self.assertEqual(self.notice()['id'],item['id']);self.assertEqual(self.notice()['status'],'UNKNOWN')

    def test_stale_recovered_symlink_or_changed_payload_fails_closed(self):
        for variant in ('stale','resolved','payload','registry','symlink'):
            with self.subTest(variant=variant):
                s,item=self.stage()
                if variant=='stale':s['readiness_checked_at']=self.now-91
                if variant=='resolved':s['readiness_episode']['status']='RESOLVED'
                if variant=='payload':
                    item['payload']['cause']='AUTHENTICATION_OPERATOR'
                    with closing(self.store.connect()) as c,c:c.execute('update notification_outbox set payload=? where id=?',(json.dumps(item['payload']),item['id']))
                if variant=='registry':
                    with closing(self.store.connect()) as c,c:c.execute("update incident_cursors set payload='{}' where source like 'gateway-operator:%'")
                self.persist(s)
                if variant=='symlink':
                    p=self.root/'runtime/gateway-recovery-state.json';p.rename(p.with_suffix('.saved'));p.symlink_to(p.with_suffix('.saved'))
                self.assertFalse(validate(self.store,item,CONFIG))
                if variant=='symlink':
                    p.unlink();p.with_suffix('.saved').rename(p)
                # Restore registry through a fresh per-subtest source transaction.
                with closing(self.store.connect()) as c,c:
                    c.execute('DELETE FROM incident_cursors WHERE source LIKE \'gateway-operator:%\'')
                    c.execute('DELETE FROM notification_outbox WHERE kind=?',(KIND,))

    def test_native_recovery_arriving_during_destination_proof_blocks_wire(self):
        self.stage();bot=fixtures.NotificationCenterTests.bot(self);original=bot.get_chat
        async def chat(cid,**kw):
            self.native(True)
            return await original(cid,**kw)
        bot.get_chat=chat
        self.assertEqual(self.send(bot),'SUPPRESSED');self.assertEqual(bot.sends,[])

    def test_current_persistent_failure_not_original_queue_age_proves_actionability(self):
        s,item=self.stage();self.now+=600;s['readiness_checked_at']=self.now;self.persist(s)
        self.assertTrue(validate(self.store,item,CONFIG))
        self.native(True);self.assertFalse(validate(self.store,item,CONFIG))

    def test_forged_notice_cannot_get_past_publication_validation(self):
        with closing(self.store.connect()) as c,c:
            ident=c.execute("insert into notification_outbox(incident_key,generation,kind,payload,status) values('gateway-readiness:forged',1,?,?,'PENDING')",(KIND,json.dumps(dict(scope='GATEWAY_READINESS',source='existing Gateway watchdog',severity='RED',requires_response=True,private_notice=True,grants_trading_permission=False)))).lastrowid
        item=get_item(self.store,ident)
        self.assertEqual(decision(item,CONFIG)['audience'],'owner')
        self.assertFalse(validate(self.store,item,CONFIG))

    def test_stable_closure_resets_on_gap_dirty_or_new_generation(self):
        s=self.open()
        for now in (2000,2060):s=observe(s,self.evidence(now,True),now)
        self.assertEqual(s['readiness_episode']['status'],'OPEN')
        e=self.evidence(2090,True);e['generation']='2:200';s=observe(s,e,2090)
        self.assertEqual(s['readiness_episode']['status'],'OPEN')
        for now in (2120,2150):
            e=self.evidence(now,True);e['generation']='2:200';s=observe(s,e,now)
        self.assertEqual(s['readiness_episode']['status'],'RESOLVED');self.assertFalse(s['readiness_requires_operator'])

    def test_crash_after_state_before_publish_reuses_one_immutable_occurrence(self):
        s=json.loads(json.dumps(self.open()));self.persist(s);publish(self.store,s);publish(self.store,s)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('select count(*) from incident_events').fetchone()[0],1)
            self.assertEqual(c.execute('select count(*) from notification_outbox where kind=?',(KIND,)).fetchone()[0],1)

    def test_auth_phase_uses_journal_private_route_without_watchdog_mirror(self):
        e=self.evidence(self.now);e['operator_observation']=dict(generation='1:100',phase='OPERATOR',at=self.now)
        s=observe({},e,self.now);self.assertTrue(s['readiness_requires_operator']);publish(self.store,s)
        self.assertIsNone(self.notice())
        collect(self.store,self.root,reader=lambda _:[])
        self.now+=1
        rows=[dict(__CURSOR='native-auth',__REALTIME_TIMESTAMP=str(self.now*1000000),MESSAGE='START_RESULT SecurityDialogDetected')]
        collect(self.store,self.root,reader=lambda _:rows)
        with closing(self.store.connect()) as c:ident=c.execute("select id from notification_outbox where kind='AUTH_SESSION_EVENT'").fetchone()[0]
        item=get_item(self.store,ident);self.assertEqual(item['payload']['queued_at'],self.now)
        self.assertTrue(validate(self.store,item,CONFIG))
        bot=fixtures.NotificationCenterTests.bot(self);self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual([x[0] for x in bot.sends],[42])

    def test_current_native_session_conflict_also_reaches_private_action_route(self):
        collect(self.store,self.root,reader=lambda _:[]);self.now+=1
        rows=[dict(__CURSOR='native-conflict',__REALTIME_TIMESTAMP=str(self.now*1000000),MESSAGE='START_RESULT ExistingSessionDetected')]
        collect(self.store,self.root,reader=lambda _:rows)
        with closing(self.store.connect()) as c:ident=c.execute("select id from notification_outbox where kind='AUTH_SESSION_EVENT'").fetchone()[0]
        self.assertTrue(validate(self.store,get_item(self.store,ident),CONFIG))
        bot=fixtures.NotificationCenterTests.bot(self);self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual([x[0] for x in bot.sends],[42])

    def test_journal_operator_proof_rejects_old_other_epoch_or_superseded_phase(self):
        stamp=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        text=stamp(990)+' START_RESULT SecurityDialogDetected'
        self.assertEqual(operator_observation(text,'1:100',900,1000)['phase'],'OPERATOR')
        self.assertIsNone(operator_observation(text,'1:100',995,1000))
        self.assertIsNone(operator_observation(text,'1:100',900,1200))
        self.assertIsNone(operator_observation(text+'\n'+stamp(999)+' START_RESULT None','1:100',900,1000))
        self.assertIsNone(operator_observation('private username text','1:100',900,1000))
        for code in ('TwoFactorConfirmationTimeout','LoginFailed','SoftRestartTimeout','LoginFailedAccountTasksRequired'):
            self.assertEqual(phase('START_RESULT '+code)[0],'OPERATOR')

    def test_early_native_auth_wait_is_a_restart_negative_gate(self):
        (self.root/'runtime/gateway-recovery-policy.json').write_text(json.dumps(dict(approved=True,account=ACCOUNT,environment='PAPER',grants_trading_permission=False,allow_during_maintenance=True)))
        (self.root/'runtime/paper-observer.latest.json').write_text(json.dumps(dict(observed_at=datetime.fromtimestamp(self.now,timezone.utc).isoformat(),complete=False,gateway_api_handshake=False)))
        from types import SimpleNamespace
        text=datetime.fromtimestamp(self.now,timezone.utc).isoformat()+' Waiting for 2FA confirmation'
        with patch.object(watchdog,'gateway_generation',return_value='1:100'),patch.object(watchdog,'generation_started_at',return_value=900),patch.object(watchdog,'unit',return_value={'ActiveState':'active'}),patch.object(watchdog.subprocess,'run',return_value=SimpleNamespace(stdout=text)):
            e=watchdog.evidence(self.root,self.now)
        self.assertTrue(e['auth_required']);self.assertEqual(e['operator_observation']['phase'],'OPERATOR')
        _,action=decide({},e,self.now);self.assertEqual(action,'NONE')

    def test_old_auth_hint_does_not_demand_action_or_override_complete_business(self):
        e=self.evidence(self.now);e['auth_required']=True
        self.assertFalse(observe({},e,self.now)['readiness_requires_operator'])
        e['operator_observation']=dict(generation='old',phase='OPERATOR',at=self.now)
        self.assertFalse(observe({},e,self.now)['readiness_requires_operator'])
        e=self.evidence(self.now,True);e['operator_observation']=dict(generation='1:100',phase='OPERATOR',at=self.now)
        self.assertEqual(observe({},e,self.now)['readiness_phase'],'HEALTHY')

    def test_expired_or_consumed_operation_cannot_become_new_restart(self):
        s=self.open();s.update(operation='STARTED',requested_at=1899)
        s=observe(s,self.evidence(1900),1900);self.assertFalse(s['readiness_requires_operator'])
        s.update(operation='OPERATOR_REQUIRED');s=observe(s,self.evidence(2600),2600)
        self.assertTrue(s['readiness_requires_operator']);self.assertEqual(s['request_id'],'original')
        _,action=decide(s,self.evidence(2600),2600);self.assertEqual(action,'NONE')

    def test_pin_uses_bounded_current_health_only_and_preserves_gates(self):
        self.co.observe('GATEWAY_RECOVERY','DEGRADED',freshness='FRESH',readiness_version=1,readiness_phase='OPERATOR_REQUIRED',reason='PRIVATE account DUQ503649')
        with patch('reporting.automatic_notifications.persistence_clear',return_value=True):s=snapshot(self.store,self.root,self.now)
        text=render_card(dict(payload=dict(links=s,observed_at=self.now)))
        self.assertIn('Gateway恢复/人工：需要本人检查',text);self.assertNotIn('PRIVATE',text);self.assertNotIn(ACCOUNT,text)
        self.now+=91
        with patch('reporting.automatic_notifications.persistence_clear',return_value=True):s=snapshot(self.store,self.root,self.now)
        self.assertEqual(s['recovery'],'未取得新版恢复探针证据')
