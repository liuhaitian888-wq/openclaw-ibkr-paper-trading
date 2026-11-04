from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from trading.audit import AuditLog
from reporting.broker_baseline import persist_readback


class BrokerBaselineTests(unittest.TestCase):
    def setup_db(self,root):
        db=root/'audit.sqlite3';AuditLog(db)
        with closing(sqlite3.connect(db)) as c,c:
            c.execute('CREATE TABLE canonical_pool_state (symbol TEXT PRIMARY KEY,has_active_order INTEGER,payload_json TEXT)')
            c.execute('INSERT INTO canonical_pool_state VALUES (?,?,?)',('PFE',0,json.dumps({'enabled':True})))
        now=datetime(2026,11,5,0,20,tzinfo=timezone.utc)
        snap=dict(observed_at=now.isoformat(),source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',
                  end_markers=['summary','positions','orders','executions'],account={'net_liquidation':{'value':1000}},
                  positions=[dict(account='DU123',conId=11031,symbol='PFE',currency='USD',position='8',avgCost=24.3)],
                  orders=[dict(account='DU123',conId=11031,symbol='PFE',order_id=1,perm_id=42,client_id=3130,order_ref='existing-protection',side='SELL',quantity='8',status='PreSubmitted',order_type='STP',tif='GTC',limit_price=0,aux_price=20)],executions=[])
        return db,snap,now

    def test_current_facts_persist_without_synthetic_fills_or_strategy_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db,snap,now=self.setup_db(root)
            result=persist_readback(db,snap,'DU123',now)
            self.assertEqual(result['status'],'CURRENT_BASELINE_MATCHED')
            self.assertEqual(result['ownership'][0]['ownership'],'UNKNOWN')
            self.assertFalse(result['grants_trading_permission'])
            with closing(sqlite3.connect(db)) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM executions').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT count(*) FROM order_requests').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT has_active_order FROM canonical_pool_state').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM current_broker_positions').fetchone()[0],1)
            self.assertEqual(len(list((root/'baseline-backups').glob('*.sqlite3'))),1)
            self.assertEqual(persist_readback(db,snap,'DU123',now)['status'],'ALREADY_PERSISTED')

    def test_opening_snapshot_immutable_and_missing_order_remains_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,snap,now=self.setup_db(Path(tmp));persist_readback(db,snap,'DU123',now)
            changed=deepcopy(snap);changed['observed_at']=(now+timedelta(seconds=1)).isoformat();changed['orders']=[];changed['positions'][0]['position']='9'
            result=persist_readback(db,changed,'DU123',now+timedelta(seconds=1))
            self.assertEqual(result['absent_prior_order_ids'],[1])
            with closing(sqlite3.connect(db)) as c:
                opening=json.loads(c.execute('SELECT payload_json FROM paper_readback_baselines').fetchone()[0])
                self.assertEqual(opening['positions'][0]['position'],'8')
                self.assertEqual(c.execute('SELECT has_active_order FROM canonical_pool_state').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT status FROM broker_orders').fetchone()[0],'PreSubmitted')
            with self.assertRaisesRegex(ValueError,'Out-of-order'):
                persist_readback(db,dict(snap,observed_at=(now-timedelta(seconds=1)).isoformat()),'DU123',now)

    def test_stale_mixed_incomplete_or_missing_order_fields_cannot_publish(self):
        for failure in ('stale','mixed','incomplete','order_fields','duplicate'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                db,snap,now=self.setup_db(Path(tmp))
                if failure=='stale':snap['observed_at']=(now-timedelta(seconds=601)).isoformat()
                if failure=='mixed':snap['positions'][0]['account']='DU999'
                if failure=='incomplete':snap['complete']=False
                if failure=='order_fields':del snap['orders'][0]['order_type']
                if failure=='duplicate':snap['positions']*=2
                with self.assertRaises(ValueError):persist_readback(db,snap,'DU123',now)
                with closing(sqlite3.connect(db)) as c:
                    self.assertEqual(c.execute('SELECT count(*) FROM broker_orders').fetchone()[0],0)

    def test_order_identity_collision_rolls_back_current_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,snap,now=self.setup_db(Path(tmp));persist_readback(db,snap,'DU123',now)
            changed=deepcopy(snap);changed['observed_at']=(now+timedelta(seconds=1)).isoformat();changed['positions'][0]['position']='99';changed['orders'][0]['perm_id']=43
            with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):
                persist_readback(db,changed,'DU123',now+timedelta(seconds=1))
            with closing(sqlite3.connect(db)) as c:
                row=json.loads(c.execute('SELECT payload_json FROM current_broker_positions').fetchone()[0]);self.assertEqual(row['position'],'8')
                self.assertEqual(c.execute('SELECT count(*) FROM paper_readback_observations').fetchone()[0],1)
