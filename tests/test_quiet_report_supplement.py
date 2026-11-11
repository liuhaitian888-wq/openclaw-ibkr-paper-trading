from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.publication_policy import prepare, digest, decision, validate
from reporting.report_schedule import BJ, enqueue_reports
from reporting.incident_telegram import report_bytes
from scripts.report_aggregation import period_for


class QuietReportSupplementTests(unittest.TestCase):
    def fixture(self, root, now):
        reports=root/'reports';reports.mkdir(exist_ok=True)
        store=IncidentStore(root/'runtime/recovery.sqlite3',clock=lambda:now.timestamp())
        self.assertEqual(enqueue_reports(store,reports,'DU123',now,transport='telegram'),'REPORT_BUNDLE')
        with closing(store.connect()) as c:
            ident,raw=c.execute('SELECT id,payload FROM notification_outbox').fetchone()
        self.assertEqual(prepare(store,{'automatic_notification_policy':'publication-v2'}),1)
        directory=reports/now.date().isoformat();directory.mkdir()
        png=directory/'DAILY.png';content=b'\x89PNG\r\n\x1a\nisolated-original'
        png.write_bytes(content)
        report=dict(report_type='DAILY',report_date=now.date().isoformat(),generated_at=now.isoformat(),
            source_snapshot_at=now.isoformat(),account_id='DU123',environment='PAPER',source_validated=True,
            image_path=str(png),image_sha256=hashlib.sha256(content).hexdigest(),trading_period=period_for('DAILY',now))
        (directory/'DAILY.json').write_text(json.dumps(report))
        return store,reports,ident,json.loads(raw),content

    def test_archived_empty_notice_allows_one_actual_frozen_png_supplement(self):
        now=datetime(2026,11,11,9,tzinfo=BJ)
        with tempfile.TemporaryDirectory() as tmp:
            store,reports,ident,payload,content=self.fixture(Path(tmp),now)
            self.assertEqual(enqueue_reports(store,reports,'DU123',now+timedelta(seconds=5),transport='telegram'),'REPORT_SUPPLEMENT')
            item=store.claim(publication_config={'automatic_notification_policy':'publication-v2'})
            self.assertEqual(item['kind'],'REPORT_SUPPLEMENT')
            self.assertEqual(decision(item,{'automatic_notification_policy':'publication-v2'})['audience'],'group')
            self.assertEqual(report_bytes(item,reports),[('买der_日报_2026-11-11.png',content)])
            store.finish(item['id'],'TELEGRAM_ACCEPTED')
            self.assertEqual(enqueue_reports(store,reports,'DU123',now+timedelta(seconds=10),transport='telegram'),'NO_SUPPLEMENT')
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT status,payload FROM notification_outbox WHERE id=?',(ident,)).fetchone()[0],'SUPPRESSED')
                self.assertEqual(c.execute('SELECT count(*) FROM notification_receipts').fetchone()[0],0)

    def test_uncertainty_reservation_receipt_tampering_or_nonempty_original_still_blocks(self):
        now=datetime(2026,11,11,9,tzinfo=BJ)
        for case in ('unknown','started','reservation','delivery','receipt','tampered','included','no_archive','wrong_reason','wrong_policy','absent_list','png'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                store,reports,ident,payload,_=self.fixture(Path(tmp),now)
                if case=='reservation':
                    RecoveryCoordinator(store.path).begin_operation('notification:outbox:'+str(ident),'delivery',{'source':'isolated-reservation'})
                else:
                    with closing(store.connect()) as c,c:
                        if case in ('unknown','started'):c.execute('UPDATE notification_outbox SET status=? WHERE id=?',(case.upper(),ident))
                        elif case=='receipt':c.execute('INSERT INTO notification_receipts VALUES (?,?)',(ident,'{}'))
                        elif case=='delivery':c.execute("INSERT INTO notification_delivery(notification_id,attempt_started_at,status) VALUES (?,?,'UNKNOWN')",(ident,now.timestamp()))
                        elif case=='no_archive':c.execute('DELETE FROM publication_archive WHERE notification_id=?',(ident,))
                        elif case=='wrong_reason':c.execute("UPDATE publication_archive SET reason='other' WHERE notification_id=?",(ident,))
                        elif case=='wrong_policy':c.execute("UPDATE publication_archive SET policy='other' WHERE notification_id=?",(ident,))
                        else:
                            payload['reason']='changed after archive'
                            if case=='included':payload['included_reports']=['DAILY']
                            elif case=='absent_list':payload.pop('included_reports')
                            elif case=='png':payload['png_artifacts']=[{'path':'untrusted'}]
                            c.execute('UPDATE notification_outbox SET payload=? WHERE id=?',(json.dumps(payload),ident))
                            if case in ('included','absent_list','png'):c.execute('UPDATE publication_archive SET payload_sha256=? WHERE notification_id=?',(digest(payload),ident))
                self.assertEqual(enqueue_reports(store,reports,'DU123',now+timedelta(seconds=5),transport='telegram'),'BLOCKED_INITIAL_UNCONFIRMED')
                with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],1)

    def test_late_predecessor_reservation_after_enqueue_blocks_claimed_supplement(self):
        now=datetime(2026,11,11,9,tzinfo=BJ)
        with tempfile.TemporaryDirectory() as tmp:
            store,reports,ident,payload,_=self.fixture(Path(tmp),now)
            self.assertEqual(enqueue_reports(store,reports,'DU123',now+timedelta(seconds=5),transport='telegram'),'REPORT_SUPPLEMENT')
            config={'automatic_notification_policy':'publication-v2'}
            item=store.claim(publication_config=config)
            self.assertTrue(validate(store,item,config))
            RecoveryCoordinator(store.path).begin_operation('notification:outbox:'+str(ident),'delivery',{'source':'isolated-late-reservation'})
            self.assertFalse(validate(store,item,config))
            with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_receipts').fetchone()[0],0)
