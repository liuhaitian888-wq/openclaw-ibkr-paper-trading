from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from reporting.market_clock import load_calendar, snapshot, collect
from reporting.incidents import IncidentStore
from reporting.notification_center import render


def at(value):
    return datetime.fromisoformat(value)


class MarketClockTests(unittest.TestCase):
    def test_us_dst_mismatch_and_core_boundary(self):
        # Europe switched back on Oct 25, US switched on Nov 1.
        s=snapshot('NASDAQ', at('2026-10-27T13:30:00+00:00'))
        self.assertEqual(s['phase'],'CORE')
        self.assertIn('柏林 10-27 14:30',s['reason'])
        self.assertEqual(snapshot('NASDAQ',at('2026-11-02T14:29:59+00:00'))['phase'],'PRE')
        self.assertEqual(snapshot('NASDAQ',at('2026-11-02T14:30:00+00:00'))['phase'],'CORE')

    def test_early_close_and_holiday_announced_at_close(self):
        s=snapshot('NASDAQ',at('2026-11-25T21:00:00+00:00'))
        self.assertEqual(s['phase'],'POST');self.assertIn('11-26 感恩节',s['reason'])
        self.assertIn('下次开市：柏林 11-27 10:00',s['reason'])
        self.assertEqual(snapshot('NASDAQ',at('2026-11-27T18:00:00+00:00'))['phase'],'POST')
        self.assertEqual(snapshot('NASDAQ',at('2026-11-27T22:00:00+00:00'))['phase'],'CLOSED')
        self.assertEqual(snapshot('NYSE',at('2026-11-27T18:00:00+00:00'))['phase'],'CLOSED')

    def test_milan_binding_and_auction_window(self):
        data=load_calendar();self.assertEqual(data['profiles']['ETFPLUS']['contract_id'],18706552)
        self.assertEqual(snapshot('ETFPLUS',at('2026-11-09T08:04:10+00:00'))['phase'],'OPEN_UNCROSS')
        self.assertEqual(snapshot('ETFPLUS',at('2026-11-09T08:04:30+00:00'))['phase'],'CORE')
        self.assertEqual(snapshot('ETFPLUS',at('2026-12-24T09:00:00+00:00'))['phase'],'HOLIDAY')
        self.assertEqual(snapshot('ETFPLUS',at('2026-06-02T09:00:00+00:00'))['phase'],'CORE') # no TAH != closed core

    def test_restart_no_historical_replay_and_unknown_once(self):
        with tempfile.TemporaryDirectory() as d:
            store=IncidentStore(Path(d)/'r.sqlite3',clock=lambda:1)
            self.assertEqual(collect(store,now=at('2026-11-09T06:00:00+00:00')),3)
            self.assertEqual(collect(store,now=at('2026-11-09T06:01:00+00:00')),0)
            self.assertEqual(collect(store,now=at('2026-11-09T22:00:00+00:00')),3)
            with closing(store.connect()) as c:
                rows=c.execute("SELECT payload FROM notification_outbox WHERE id>3").fetchall()
            self.assertTrue(all('观察有间断' in json.loads(r[0])['reason'] for r in rows))
            self.assertEqual(collect(store,now=at('2026-11-09T21:00:00+00:00')),0)
            self.assertEqual(collect(store,now=at('2027-01-02T12:00:00+00:00')),3)
            self.assertEqual(collect(store,now=at('2027-01-03T12:00:00+00:00')),0)

    def test_private_routing_and_concise_render(self):
        config=dict(audience_mode='shared_group',chat_id=-10,owner_user_id=22,owner_private_chat_id=22,owner_private_verified=True)
        item=dict(id=1,kind='MARKET_SESSION',incident_key='market-session:test',payload={'reason':'米兰开市'})
        result=render(item,config,1)
        self.assertEqual(result['chat_id'],22);self.assertEqual(result['text'],'米兰开市')

    def test_announced_future_rule_change_is_not_silently_ignored(self):
        self.assertEqual(snapshot('NASDAQ',at('2026-12-06T21:00:00+00:00'))['phase'],'UNKNOWN')
        self.assertEqual(snapshot('ETFPLUS',at('2026-12-07T10:00:00+00:00'))['phase'],'CORE')

    def test_requires_timezone(self):
        with self.assertRaises(ValueError):snapshot('NASDAQ',datetime(2026,11,9))

    def test_pending_obsolete_phases_superseded_but_attempts_preserved(self):
        from reporting.notification_center import stale_schedule
        with tempfile.TemporaryDirectory() as d:
            store=IncidentStore(Path(d)/'r.sqlite3',clock=lambda:1)
            collect(store,now=at('2026-11-09T06:00:00+00:00'))
            with closing(store.connect()) as c,c:
                c.execute("UPDATE notification_outbox SET status='UNKNOWN' WHERE id=1")
            collect(store,now=at('2026-11-09T22:00:00+00:00'))
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT status FROM notification_outbox WHERE id=1').fetchone()[0],'UNKNOWN')
                self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE status='SUPERSEDED'").fetchone()[0],2)
            state=snapshot('NASDAQ',at('2026-11-09T14:00:00+00:00'))
            self.assertTrue(stale_schedule({'kind':'MARKET_SESSION','payload':state},at('2026-11-09T14:30:00+00:00').timestamp()))

    def test_continuous_observation_does_not_claim_a_gap_at_normal_open(self):
        with tempfile.TemporaryDirectory() as d:
            store=IncidentStore(Path(d)/'r.sqlite3',clock=lambda:1)
            for minute in range(20,31):
                collect(store,now=at(f'2026-11-09T14:{minute}:00+00:00'))
            with closing(store.connect()) as c:
                rows=c.execute("SELECT payload FROM notification_outbox WHERE id>3").fetchall()
            self.assertEqual(len(rows),2)
            self.assertTrue(all('观察有间断' not in json.loads(r[0])['reason'] for r in rows))
