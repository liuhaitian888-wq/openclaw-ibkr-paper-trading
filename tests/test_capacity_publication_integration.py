"""Real isolated capacity producer + publication policy contract."""
from contextlib import closing
from pathlib import Path
import tempfile
import time
import unittest
from reporting.capacity import _publish, _save
from reporting.incidents import IncidentStore
from reporting.publication_policy import prepare, validate, decision, archive_claimed


class CapacityPublicationIntegrationTests(unittest.TestCase):
    def test_real_critical_event_requires_fresh_producer_evidence_and_routes_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();now=time.time()
            store=IncidentStore(root/'runtime/recovery.sqlite3',clock=lambda:now)
            config={'automatic_notification_policy':'publication-v2'}
            prepare(store,config)
            data={'samples':[{'at':now,'total_bytes':32*1024**3,'available_bytes':1024**3}],
                  'risk':{'level':2,'growth':{'days_to_full':None}},'inventory':{}}
            _save(root,data);_publish(root,data)
            item=store.claim(publication_config=config)
            self.assertIsNotNone(item)
            self.assertEqual(decision(item,config)['audience'],'owner')
            self.assertEqual(decision(item,config)['public_view'],'capacity_action')
            self.assertTrue(validate(store,item,config))
            store.clock=lambda:now+901
            self.assertFalse(validate(store,item,config))

    def test_recovery_before_wire_invalidates_critical_without_creating_recovery_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();now=time.time()
            store=IncidentStore(root/'runtime/recovery.sqlite3',clock=lambda:now)
            config={'automatic_notification_policy':'publication-v2'}
            prepare(store,config)
            data={'samples':[{'at':now,'total_bytes':32*1024**3,'available_bytes':1024**3}],
                  'risk':{'level':2,'growth':{'days_to_full':None}},'inventory':{}}
            _save(root,data);_publish(root,data)
            item=store.claim(publication_config=config)
            self.assertTrue(validate(store,item,config))
            data['risk']['level']=0;data['samples'][-1]['available_bytes']=16*1024**3
            _save(root,data);_publish(root,data)
            self.assertFalse(validate(store,item,config))
            self.assertTrue(archive_claimed(store,item,config))
            self.assertIsNone(store.claim(publication_config=config))
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM incident_events').fetchone()[0],2)
                self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0],'SUPPRESSED')
