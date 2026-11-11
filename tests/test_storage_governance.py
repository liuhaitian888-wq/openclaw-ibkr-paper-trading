from contextlib import closing
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from reporting import storage_policy as policy
from reporting.storage_archive import Archive, CHUNK, allowed


class FixtureSource:
    def __init__(self, files):
        self.files = files
        self.version = 1
        self.fail = False

    def fetch(self, path, offset=None, length=0):
        if self.fail:
            raise TimeoutError('fixture transport interruption')
        data = self.files[path]
        return dict(identity=[1, self.version, len(data), 100, 100], size=len(data),
            bytes=data[offset:offset+length] if offset is not None else None)


class StorageGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'state'
        (self.root/'runtime').mkdir(parents=True)
        self.destination = Path(self.temp.name).resolve()/'archive'

    def arm(self):
        (self.root/'runtime/storage-policy.json').write_text(json.dumps(policy.POLICY))

    def disk(self, free):
        return SimpleNamespace(f_bavail=int(free*policy.GIB), f_blocks=40*policy.GIB, f_frsize=1)

    def test_policy_only_withholds_optional_writes_and_never_deletes(self):
        self.assertEqual(policy.decision(self.root,'PUBLIC_SCREENING')['state'],'POLICY_UNARMED')
        self.arm()
        self.assertFalse(policy.decision(self.root,'PUBLIC_SCREENING',disk=self.disk(7))['allowed'])
        self.assertTrue(policy.decision(self.root,'PUBLIC_SCREENING',disk=self.disk(15))['allowed'])
        with self.assertRaises(PermissionError):
            policy.decision(self.root,'ORDER_RECEIPTS',disk=self.disk(1))
        sentinel=self.root/'trading_audit.sqlite3';sentinel.write_text('immutable core fixture')
        with patch.object(policy.os,'statvfs',return_value=self.disk(7)):
            for _ in range(200):policy.preflight(self.root,'PUBLIC_SCREENING')
        self.assertEqual(sentinel.read_text(),'immutable core fixture')
        self.assertLess((self.root/'runtime/storage-budget-events.json').stat().st_size,64*1024)
        self.assertEqual(policy.read(self.root)['event_count'],1)

    def test_quota_symlink_and_unknown_metadata_fail_closed(self):
        self.arm();folder=self.root/'screening/snapshots';folder.mkdir(parents=True)
        (folder/'outside').symlink_to('/tmp')
        with patch.object(policy.os,'statvfs',return_value=self.disk(15)):
            self.assertFalse(policy.preflight(self.root,'PUBLIC_SCREENING')['allowed'])
        (self.root/'runtime/storage-policy.json').write_text('{"approved":true}')
        self.assertFalse(policy.preflight(self.root,'PUBLIC_DIRECTORY')['allowed'])

    def test_optional_producer_stops_before_network_or_db_constructor(self):
        from scripts.refresh_broad_screening import run
        self.arm()
        (self.root/'runtime/screening-policy.json').write_text(json.dumps(dict(approved=True,environment='PAPER',public_research_readonly=True,grants_trading_permission=False)))
        with patch.object(policy.os,'statvfs',return_value=self.disk(7)), patch('scripts.refresh_broad_screening.SecretaryArchive',side_effect=AssertionError('must not open DB')):
            self.assertEqual(run(self.root)['state'],'DEFERRED_CAPACITY')
        from reporting.security_directory import refresh
        with patch.object(policy.os,'statvfs',return_value=self.disk(7)):
            self.assertEqual(refresh(object(),self.root,loader=lambda *_:self.fail('must not fetch'))['state'],'DEFERRED_CAPACITY')

    def test_each_blob_is_bounded_and_prior_evidence_is_not_overwritten(self):
        self.arm();folder=self.root/'screening/snapshots/fixture';folder.mkdir(parents=True)
        path=folder/'1.json'
        with patch.object(policy.os,'statvfs',return_value=self.disk(15)):
            self.assertEqual(policy.write_blob(self.root,'PUBLIC_SCREENING',path,b'fixture'),'WRITTEN')
            self.assertEqual(policy.write_blob(self.root,'PUBLIC_SCREENING',path,b'fixture'),'DEDUPLICATED')
            with self.assertRaises(ValueError):policy.write_blob(self.root,'PUBLIC_SCREENING',path,b'different')
            with self.assertRaises(ValueError):policy.write_blob(self.root,'PUBLIC_SCREENING',folder/'2.json',b'x'*(6*policy.MIB))
        self.assertEqual(path.read_bytes(),b'fixture')

    def test_public_archive_allowlist_excludes_financial_internal_history(self):
        self.assertTrue(allowed('screening/snapshots/schedule_after-close_2026-11-10/9.json'))
        self.assertTrue(allowed('security-directory/snapshots/fixture/nasdaqlisted.txt'))
        self.assertFalse(allowed('security-directory/fixture/nasdaqlisted.txt'))
        for name in ('trading_audit.sqlite3','runtime/recovery.sqlite3','secretary-oauth/state_5.sqlite',
            'archives/audit/old.sqlite3','screening/snapshots/../manifest.json','screening/snapshots/run/receipt.json'):
            self.assertFalse(allowed(name))

    def test_resume_checksum_dedup_and_restore_without_source_deletion(self):
        path='screening/snapshots/fixture/1.json';source=FixtureSource({path:b'a'*(CHUNK+73)})
        archive=Archive(self.destination,quota=20*CHUNK,free_floor=0)
        plan=archive.plan(source,[path],execute=True)
        part=archive.batch(source,plan['id'],max_bytes=CHUNK)
        self.assertEqual(part['state'],'PARTIAL')
        done=archive.batch(source,plan['id'],max_bytes=CHUNK)
        self.assertEqual(done['state'],'COPIED')
        verified=archive.verify_restore(plan['id'])
        self.assertEqual(verified['state'],'RESTORE_VERIFIED')
        restored=self.destination/'verified-restores'/plan['id']/path
        self.assertEqual(restored.read_bytes(),source.files[path])
        self.assertFalse(verified['source_deletion_allowed'])
        self.assertEqual(archive.cleanup_dry_run(plan['id'])['approved_reclaim_bytes'],0)
        other='screening/snapshots/another/1.json';source.files[other]=source.files[path]
        again=archive.plan(source,[other],execute=True);copied=archive.batch(source,again['id'])
        self.assertGreater(copied['batches'][-1]['deduplicated_bytes'],0)

    def test_changed_source_and_corrupt_chunks_require_reconciliation(self):
        path='screening/snapshots/fixture/1.json';source=FixtureSource({path:b'x'*(CHUNK+1)})
        archive=Archive(self.destination,quota=20*CHUNK,free_floor=0)
        job=archive.plan(source,[path],execute=True);archive.batch(source,job['id'],max_bytes=CHUNK)
        source.version=2
        with self.assertRaises(RuntimeError):archive.batch(source,job['id'])
        self.assertEqual(archive.load(job['id'])['state'],'NEEDS_RECONCILIATION')
        source.version=1
        # An uncertain source identity is not silently resumed even if it appears again.
        with self.assertRaises(ValueError):archive.batch(source,job['id'])

    def test_read_transport_interruption_resumes_but_bad_checksum_does_not_verify(self):
        path='screening/snapshots/fixture/1.json';source=FixtureSource({path:b'z'*(CHUNK+1)})
        archive=Archive(self.destination,quota=20*CHUNK,free_floor=0)
        job=archive.plan(source,[path],execute=True)
        archive.batch(source,job['id'],max_bytes=CHUNK)
        source.fail=True
        with self.assertRaises(TimeoutError):archive.batch(source,job['id'])
        self.assertEqual(archive.load(job['id'])['state'],'PARTIAL')
        source.fail=False
        copied=archive.batch(source,job['id'])
        chunk=self.destination/'chunks'/copied['files'][0]['chunks'][0]['sha256']
        chunk.write_bytes(b'corrupt fixture')
        with self.assertRaises(ValueError):archive.verify_restore(job['id'])
        self.assertFalse(archive.load(job['id'])['restored'])
        self.assertEqual(source.files[path],b'z'*(CHUNK+1))

    def test_low_target_space_quota_and_no_plan_side_effect(self):
        path='screening/snapshots/fixture/manifest.json';source=FixtureSource({path:b'{}'})
        archive=Archive(self.destination,quota=20*CHUNK,free_floor=100)
        with patch('reporting.storage_archive.shutil.disk_usage',return_value=SimpleNamespace(free=99)):
            with self.assertRaises(OSError):archive.plan(source,[path])
        self.assertFalse(self.destination.exists())
        with self.assertRaises(OSError):Archive(self.destination,quota=1,free_floor=0).plan(source,[path])
        self.assertFalse(self.destination.exists())
