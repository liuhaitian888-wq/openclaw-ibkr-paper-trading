from contextlib import closing, redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from reporting.backup_verification import verify_archive, BackupVerificationError, DATABASE_FILES


class BackupVerificationTests(unittest.TestCase):
    def fixture(self, root, *, mutate=None, extras=(), corrupt=False, invalid_gzip=False, duplicate_json=False):
        files={};items=[]
        for source,name in DATABASE_FILES.items():
            p=root/('fixture-'+name[:-3])
            with closing(sqlite3.connect(p)) as c,c:
                c.execute('CREATE TABLE evidence(state TEXT)')
                c.execute("INSERT INTO evidence VALUES('UNKNOWN')")
            raw=b'not a database' if corrupt else p.read_bytes()
            packed=gzip.compress(raw)
            if invalid_gzip:
                damaged=bytearray(packed);damaged[-8]^=1;packed=bytes(damaged)
            files[name]=packed
            items.append(dict(source=source,status='BACKED_UP',file=name,compressed_bytes=len(packed),sha256_uncompressed=hashlib.sha256(raw).hexdigest()))
        manifest=dict(created_at='20261109T234709.896409Z',items=items,cross_database_atomic=False,restore_requires_maintenance_and_broker_reconciliation=True)
        if mutate:mutate(manifest)
        files['backup.json']=json.dumps(manifest).encode()
        if duplicate_json:
            files['backup.json']=files['backup.json'].replace(b'\"created_at\":',b'\"created_at\":\"20260101T000000Z\",\"created_at\":',1)
        p=root/'source.tar'
        with tarfile.open(p,'w:') as t:
            for name,data in files.items():
                member=tarfile.TarInfo(name);member.size=len(data);t.addfile(member,io.BytesIO(data))
            for member,data in extras:t.addfile(member,io.BytesIO(data) if data else None)
        return p

    def test_four_readonly_copies_preserve_uncertainty_originals_and_restore_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root);before=archive.read_bytes();sentinel=root/'financial_ledger.sqlite3';sentinel.write_bytes(b'keep')
            result=verify_archive(archive,root,expected_archive_sha256=hashlib.sha256(before).hexdigest())
            self.assertEqual(result['state'],'CHECKED_COPY');self.assertEqual(len(result['databases']),4)
            self.assertFalse(result['source_authenticated']);self.assertFalse(result['cross_database_consistency_verified']);self.assertFalse(result['grants_restore_permission'])
            self.assertEqual(archive.read_bytes(),before);self.assertEqual(sentinel.read_bytes(),b'keep')
            work=Path(result['workdir']);self.assertEqual(work.stat().st_mode&0o777,0o700)
            self.assertEqual((work/'receipt.json').stat().st_mode&0o777,0o600)
            for item in result['databases']:
                p=work/item['file'];self.assertEqual(p.stat().st_mode&0o777,0o600)
                with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as c:
                    self.assertEqual(c.execute('SELECT state FROM evidence').fetchone()[0],'UNKNOWN')
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),item['sha256'])
            self.assertFalse(any(work.glob('*-wal')));self.assertFalse(any(work.glob('*-shm')))

    def test_rejects_traversal_extra_links_and_duplicate_members_before_database_copy(self):
        cases=[('../PRIVATE_CANARY',tarfile.REGTYPE),('/PRIVATE_CANARY',tarfile.REGTYPE),('extra',tarfile.REGTYPE),('financial_ledger.sqlite3.gz',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]
        for name,kind in cases:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);member=tarfile.TarInfo(name);member.type=kind;member.linkname='/outside';archive=self.fixture(root,extras=[(member,b'')])
                with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
                self.assertNotIn('PRIVATE_CANARY',str(caught.exception))
                if caught.exception.workdir:self.assertFalse(any(Path(caught.exception.workdir).glob('*.sqlite3')))
                self.assertTrue(archive.exists())

    def test_incomplete_ambiguous_or_unbounded_manifest_fails(self):
        changes=[lambda m:m['items'].pop(),lambda m:m['items'].__setitem__(1,m['items'][0]),lambda m:m['items'][0].update(file='../escape'),lambda m:m['items'][0].update(status='MISSING_NOT_PUBLISHED'),lambda m:m.update(restore_requires_maintenance_and_broker_reconciliation=False),lambda m:m['items'][0].update(compressed_bytes=True)]
        for change in changes:
            with self.subTest(change=changes.index(change)),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);archive=self.fixture(root,mutate=change)
                with self.assertRaises(BackupVerificationError):verify_archive(archive,root)

    def test_checksum_corruption_and_matching_hash_invalid_sqlite_preserve_failure_receipt(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);archive=self.fixture(root,corrupt=corrupt,mutate=None if corrupt else lambda m:m['items'][0].update(sha256_uncompressed='0'*64))
                with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
                self.assertEqual(caught.exception.code,'SQLITE_INVALID' if corrupt else 'HASH_MISMATCH')
                receipt=json.loads((Path(caught.exception.workdir)/'receipt.json').read_text());self.assertEqual(receipt['state'],'FAILED');self.assertFalse(receipt['grants_restore_permission'])
                self.assertTrue(archive.exists())

    def test_archive_anchor_and_decoded_byte_deadline_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root)
            with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root,expected_archive_sha256='0'*64)
            self.assertEqual(caught.exception.code,'ARCHIVE_HASH_MISMATCH')
            with patch('reporting.backup_verification.MAX_DB_BYTES',100):
                with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
            self.assertEqual(caught.exception.code,'DECODED_BYTE_LIMIT')
            with patch('reporting.backup_verification.SQLITE_SECONDS',0):
                with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
            self.assertEqual(caught.exception.code,'DEADLINE_EXCEEDED')
            with patch('reporting.backup_verification.MAX_SECONDS',0):
                with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
            self.assertEqual(caught.exception.code,'DEADLINE_EXCEEDED')

    def test_corrupt_gzip_crc_fails_with_partial_evidence_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root,invalid_gzip=True)
            with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
            self.assertEqual(caught.exception.code,'INVALID_GZIP')
            receipt=json.loads((Path(caught.exception.workdir)/'receipt.json').read_text())
            self.assertEqual(receipt['state'],'FAILED');self.assertTrue(archive.exists())

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root,duplicate_json=True)
            with self.assertRaises(BackupVerificationError) as caught:verify_archive(archive,root)
            self.assertEqual(caught.exception.code,'DUPLICATE_JSON_KEY')

    def test_failed_checks_close_all_owned_descriptors_without_gc(self):
        import gc
        import os
        inventory='/proc/self/fd' if Path('/proc/self/fd').is_dir() else '/dev/fd'
        if not Path(inventory).is_dir():self.skipTest('No descriptor inventory')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root,corrupt=True);before=len(os.listdir(inventory));enabled=gc.isenabled();gc.disable()
            try:
                for _ in range(10):
                    with self.assertRaises(BackupVerificationError):verify_archive(archive,root)
                self.assertLessEqual(len(os.listdir(inventory)),before+1)
            finally:
                if enabled:gc.enable()

    def test_source_symlink_refused_and_cli_safe_json(self):
        from scripts.verify_state_backup import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=self.fixture(root);link=root/'link.tar';link.symlink_to(archive)
            with self.assertRaises(BackupVerificationError):verify_archive(link,root)
            out=io.StringIO()
            with redirect_stdout(out):status=main([str(archive),'--output-root',str(root)])
            self.assertEqual(status,0);self.assertEqual(json.loads(out.getvalue())['state'],'CHECKED_COPY')
