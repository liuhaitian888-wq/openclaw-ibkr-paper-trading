from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reporting.agent_secretary import SecretaryArchive
from reporting.incidents import IncidentStore
from reporting import market_subscriptions as m


class MarketSubscriptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
        self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:100000)
        IncidentStore(self.root/'runtime/recovery.sqlite3')
        self.state=dict(identity=True,connected=True,upstream_connected=True,last_server_reply=100000,
                        quotes={'AAPL':dict(bid=100,ask=101,bid_at=100000,ask_at=100000,data_type=1)},market_types={'AAPL':1},market_errors={})
        self.save()
        with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c,c:
            c.execute('CREATE TABLE canonical_pool_state(symbol TEXT,current_layer TEXT,updated_at TEXT)')
            c.executemany('INSERT INTO canonical_pool_state VALUES(?,?,?)',[('AAPL','WATCH_POOL','now'),('ZZZ','MASTER_UNIVERSE','now')])

    def save(self):
        with closing(sqlite3.connect(self.root/'runtime/recovery.sqlite3')) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES(1,?)',(json.dumps(self.state),))

    def owner(self,key,text='/market_register'):
        self.a.append(key,'der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':text})

    def declaration(self,**kw):
        return dict(package='fixture feed',environment='LIVE',realtime=True,paper_shared=False,symbols=['AAPL'],active=True,**kw)

    def test_declared_live_not_shared_never_implies_paper_entitlement(self):
        self.owner('a');m.register(self.a,'a',self.declaration())
        row=m.view(self.root,self.a,now=100000)['rows'][0]
        self.assertEqual(row['subscription'],'UNREGISTERED');self.assertEqual(row['observed_quote'],'REALTIME_HEALTHY')
        self.owner('b');d=self.declaration();d['paper_shared']=True;m.register(self.a,'b',d)
        self.assertEqual(m.view(self.root,self.a,now=100000)['rows'][0]['subscription'],'OWNER_REALTIME')
        # Replaying an earlier operation cannot revert a later declaration.
        m.register(self.a,'a',self.declaration())
        self.assertTrue(m.packages(self.a)[0]['paper_shared'])
        d['active']=False;self.owner('c');m.register(self.a,'c',d)
        self.assertEqual(m.view(self.root,self.a,now=100000)['rows'][0]['subscription'],'UNREGISTERED')

    def test_unknown_attention_is_not_canonical_eligibility_and_higher_layers_are_eligible(self):
        self.owner('w');m.watch(self.a,'w','MSFT')
        self.assertEqual([r['symbol'] for r in m.view(self.root,self.a,eligible=True,now=100000)['rows']],['AAPL'])
        rows=m.view(self.root,self.a,now=100000)['rows']
        self.assertFalse(next(r for r in rows if r['symbol']=='MSFT')['canonical_layer_verified'])
        self.assertEqual(next(r for r in rows if r['symbol']=='MSFT')['observed_quote'],'UNKNOWN')

    def test_delayed_and_stale_are_not_permission_failures_and_no_broker_calls(self):
        self.owner('a');d=self.declaration();d['paper_shared']=True;m.register(self.a,'a',d)
        self.state['market_types']['AAPL']=3;self.save()
        self.assertEqual(m.quote_status(self.root,'AAPL',100000),'DELAYED')
        self.state['market_types']['AAPL']=1;self.state['quotes']['AAPL']['bid_at']=99900;self.save()
        self.assertEqual(m.quote_status(self.root,'AAPL',100000),'REALTIME_STALE')
        with patch('subprocess.run') as run:
            result=m.check(self.a,self.root,periodic=True,now=100000)
            self.assertEqual(result['permission_denied'],[])
            self.assertIsNone(m.check(self.a,self.root,periodic=True,now=100000))
        run.assert_not_called()
        self.assertIsNone(IncidentStore(self.root/'runtime/recovery.sqlite3').claim())

    def test_permission_prompt_dedupes_and_unknown_delivery_never_replays(self):
        self.state['market_errors']={'AAPL':{'code':354,'observed_at':100000}};self.save()
        m.check(self.a,self.root,now=100000);m.check(self.a,self.root,now=100000)
        s=IncidentStore(self.root/'runtime/recovery.sqlite3');item=s.claim()
        self.assertEqual(item['kind'],'AUTH_MARKET_SUBSCRIPTION')
        s.finish(item['id'],'UNKNOWN')
        m.check(self.a,self.root,now=100000);self.assertIsNone(s.claim())
        self.state['last_server_reply']=90000;self.save()
        self.assertEqual(m.check(self.a,self.root,now=100000)['permission_denied'],[])

    def test_pagination_and_owner_validation(self):
        with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c,c:
            c.executemany('INSERT INTO canonical_pool_state VALUES(?,?,?)',[(f'S{i:02d}','SCAN_POOL','now') for i in range(35)])
        first=m.view(self.root,self.a,now=100000);second=m.view(self.root,self.a,after=first['next_after'],now=100000)
        self.assertEqual(len(first['rows']),20)
        self.assertFalse({r['symbol'] for r in first['rows']} & {r['symbol'] for r in second['rows']})
        with self.assertRaises(PermissionError):m.register(self.a,'non-owner',self.declaration())
        self.owner('bad')
        for field,value in [('paper_shared','true'),('symbols',['AAPL"']),('active',1)]:
            d=self.declaration();d[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.register(self.a,'bad',d)

    def test_unregistered_observed_symbols_are_sampled_without_inventing_entitlements(self):
        result=m.check(self.a,self.root,now=100000)
        self.assertEqual(result['rows'][0]['symbol'],'AAPL')
        self.assertEqual(result['rows'][0]['subscription'],'UNREGISTERED')
        self.assertEqual(result['rows'][0]['observed_quote'],'REALTIME_HEALTHY')
        self.state['market_errors']={'AAPL':{'code':354,'observed_at':99990}};self.save()
        self.assertEqual(m.quote_status(self.root,'AAPL',100000),'REALTIME_HEALTHY')

    def test_native_command_classification_and_menu(self):
        from reporting.secretary_controls import process_controls,menu_commands
        from reporting.secretary_queue import initialize,accept_update
        initialize(self.a)
        cfg=dict(owner_user_id=123,owner_private_chat_id=123,owner_private_verified=True,bot_username='fixture')
        for uid,text in enumerate(['/marketdata','/universe','/eligible','/watch TSLA','/market_check'],1):
            u=dict(update_id=uid,message=dict(chat=dict(id=123,type='private'),date=100000,message_id=uid,text=text,**{'from':dict(id=123,is_bot=False)}))
            self.assertTrue(accept_update(self.a,u,cfg,armed_at=1))
        with patch('subprocess.run') as run:process_controls(self.a,self.root,cfg)
        run.assert_not_called()
        with closing(self.a.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM secretary_runs WHERE model='PYTHON_CONTROL' AND state='SUCCEEDED'").fetchone()[0],5)
        self.assertTrue({'marketdata','universe','eligible','market_check'}.issubset({x[0] for x in menu_commands()}))
