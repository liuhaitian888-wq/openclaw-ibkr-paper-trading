from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from trading.gateway_readiness import observe, publish
from trading.gateway_recovery import decide, ACCOUNT, ENDS
from reporting.incidents import IncidentStore
from reporting.gateway_session_events import phase
from reporting.automatic_notifications import prepare
from reporting.notification_center import render
from test_automatic_notifications import CONFIG


class GatewayReadinessTests(unittest.TestCase):
    def evidence(self, now, healthy=False):
        return dict(approved=True, service='active', generation='1:100',
                    native=dict(connected=healthy, identity=healthy, upstream_connected=healthy,
                                dirty=not healthy, ends=list(ENDS) if healthy else [],
                                last_server_reply=now if healthy else 0),
                    readback=dict(complete=healthy, account_id=ACCOUNT, environment='PAPER',
                                  at=now, server_time=now if healthy else 0, gateway_api_handshake=True))

    def open(self):
        state = dict(operation='RECOVERED', request_id='prior', last_attempt=100)
        for now in range(1000, 1901, 30):
            state, action = decide(state, self.evidence(now), now)
            self.assertEqual(action, 'NONE')
            state = observe(state, self.evidence(now), now)
        self.assertEqual(state['readiness_episode']['status'], 'OPEN')
        return state

    def recover(self, state, start=2000):
        for now in range(start, start+61, 30):
            state = observe(state, self.evidence(now, True), now)
        return state

    def test_handshake_only_alert_preserves_restart_outcome_and_budget(self):
        state = self.open()
        self.assertEqual(state['operation'], 'RECOVERED')
        self.assertEqual(state['request_id'], 'prior')
        self.assertEqual(state['last_attempt'], 100)
        self.assertEqual(state['readiness_episode']['cause'], 'BUSINESS_READINESS_UNVERIFIED')

    def test_repeat_snapshot_missing_field_stale_gap_and_generation_reset_do_not_open(self):
        for variant in ('same', 'stale', 'missing', 'generation', 'gap'):
            state = {}
            for now in range(1000, 1901, 30):
                e = self.evidence(now)
                if variant == 'same': e['readback']['at'] = 1000
                if variant == 'stale': e['readback']['at'] = 0
                if variant == 'missing': e['readback'].pop('gateway_api_handshake')
                if variant == 'generation': e['generation'] = str(now)
                if variant == 'gap' and now in (1300, 1330, 1360, 1390): continue
                state = observe(state, e, now)
            self.assertNotIn('readiness_episode', state, variant)

    def test_explicit_auth_and_identity_need_attention_without_restart_or_cause_invention(self):
        for field, cause in (('auth_required', 'AUTHENTICATION_OPERATOR'),
                             ('identity_mismatch', 'IDENTITY_UNVERIFIED')):
            e = self.evidence(1000); e[field] = True
            state, action = decide({}, e, 1000)
            state = observe(state, e, 1000)
            self.assertEqual(action, 'NONE')
            self.assertEqual(state['readiness_episode']['cause'], cause)
        e = self.evidence(1000, True); e['auth_required'] = True
        self.assertNotIn('readiness_episode', observe({}, e, 1000))

    def test_transient_upstream_loss_never_demands_authentication(self):
        state = {}
        for now in range(1000, 1901, 30):
            e = self.evidence(now, True)
            if now < 1600:
                e['native']['upstream_connected'] = False
                e['readback']['complete'] = False
            state = observe(state, e, now)
        self.assertNotIn('readiness_episode', state)

    def test_closure_requires_complete_fresh_post_episode_proof_stability_and_current_generation(self):
        for variant in ('old', 'dirty', 'wrong_account', 'server_time', 'heartbeat'):
            state = self.open()
            for now in (2000, 2030, 2060):
                e = self.evidence(now, True)
                if variant == 'old': e['readback']['at'] = 1890
                if variant == 'dirty': e['native']['dirty'] = True
                if variant == 'wrong_account': e['readback']['account_id'] = 'OTHER'
                if variant == 'server_time': e['readback']['server_time'] = 0
                if variant == 'heartbeat': e['native']['last_server_reply'] = 0
                state = observe(state, e, now)
            self.assertEqual(state['readiness_episode']['status'], 'OPEN', variant)
        state = self.open()
        state = observe(state, self.evidence(2000, True), 2000)
        state = observe(state, self.evidence(2060, True), 2060)  # Missing polls reset stability.
        self.assertEqual(state['readiness_episode']['status'], 'OPEN')
        e = self.evidence(2090, True); e['generation'] = '2:200'
        state = observe(state, e, 2090)
        self.assertEqual(state['readiness_episode']['status'], 'OPEN')
        state = self.recover(self.open())
        self.assertEqual(state['readiness_episode']['status'], 'RESOLVED')

    def test_persist_then_ingest_retry_is_idempotent_and_new_episode_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = IncidentStore(Path(tmp)/'runtime/recovery.sqlite3', clock=lambda: 1900)
            state = json.loads(json.dumps(self.open()))  # Restart after state commit, before publication.
            publish(store, state); publish(store, state)
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('select count(*) from notification_outbox').fetchone()[0], 1)
            state = self.recover(state); publish(store, state); publish(store, state)
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('select state from incidents').fetchone()[0], 'RESOLVED')
                self.assertEqual(c.execute('select count(*) from incident_events').fetchone()[0], 2)
            old_id = state['readiness_episode']['id']
            e = self.evidence(2100); e['auth_required'] = True
            state = observe(state, e, 2100); publish(store, state)
            self.assertNotEqual(state['readiness_episode']['id'], old_id)
            self.assertNotIn('readiness_healthy_since', state)
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('select count(*) from incident_events').fetchone()[0], 3)

    def test_existing_projection_keeps_detail_private_for_shared_policy_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000]
            store = IncidentStore(Path(tmp)/'runtime/recovery.sqlite3', clock=lambda: now[0])
            prepare(store, CONFIG)
            now[0] = 1900; publish(store, self.open())
            prepare(store, CONFIG); now[0] += 2; prepare(store, CONFIG)
            with closing(store.connect()) as c:
                row = c.execute("select id,incident_key,generation,kind,payload,status from notification_outbox where kind='AUTOMATIC_STATUS'").fetchone()
                self.assertIsNotNone(row)
                item = dict(zip(('id','incident_key','generation','kind','payload','status'),row))
                item['payload'] = json.loads(item['payload'])
            view = render(item, CONFIG, now[0])
            self.assertEqual(view['audience'], 'group')
            self.assertIn('仍待核验', view['text'])
            self.assertNotIn('需要人工检查', view['text'])
            self.assertNotIn(ACCOUNT, view['text'])
            self.assertFalse(item['payload']['grants_trading_permission'])

    def test_exact_automater_failure_phases_are_sanitized_not_raw_private_messages(self):
        for prefix in ('START_RESULT ', 'RESTART_RESULT '):
            for code in ('TwoFactorConfirmationTimeout', 'SecurityDialogDetected', 'LoginFailed',
                         'LoginFailedAccountTasksRequired', 'InitializationTimeout', 'SoftRestartTimeout',
                         'UnknownMessageWindowDetected', 'RestartedProcessNotFound'):
                self.assertEqual(phase('2026-date '+prefix+code)[0], 'OPERATOR')
        self.assertEqual(phase('2026-date Auto-restart token expired')[0], 'OPERATOR')
        self.assertIn('正在等待IBKR手机确认', phase('2026-date Waiting for 2FA confirmation')[1])
        self.assertIsNone(phase('PRIVATE password error arbitrary text'))
