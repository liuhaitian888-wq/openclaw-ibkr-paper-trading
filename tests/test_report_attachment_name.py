from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,json,unittest
from reporting.incident_telegram import report_bytes,report_filename

class AttachmentNameTests(unittest.TestCase):
 def test_frozen_content_name_uses_bound_identity_and_preserves_every_byte(self):
  with TemporaryDirectory() as tmp:
   root=Path(tmp);data=b'\x89PNG\r\n\x1a\noriginal';digest=hashlib.sha256(data).hexdigest()
   png=root/(digest+'.png');png.write_bytes(data)
   report=dict(report_type='DAILY',report_date='2026-11-11',image_sha256=digest,environment='PAPER',source_validated=True)
   metadata=json.dumps(report).encode();manifest=root/(hashlib.sha256(metadata).hexdigest()+'.json');manifest.write_bytes(metadata)
   item=dict(kind='REPORT_SUPPLEMENT',payload=dict(png_artifacts=[dict(path=str(png),sha256=digest)],report_manifests=[dict(path=str(manifest),sha256=hashlib.sha256(metadata).hexdigest())]))
   self.assertEqual(report_bytes(item,root),[('买der_日报_2026-11-11.png',data)])
   self.assertEqual(png.read_bytes(),data);self.assertEqual(manifest.read_bytes(),metadata)
 def test_only_fixed_labels_and_canonical_dates_can_enter_public_filename(self):
  self.assertEqual(report_filename(dict(report_type='WEEKLY',report_date='2026-11-09')),'买der_周报_2026-11-09.png')
  self.assertEqual(report_filename(dict(report_type='MONTHLY',report_date='2026-11-01')),'买der_月报_2026-11-01.png')
  self.assertEqual(report_filename({}),'买der_账户报告.png')
  for kind,day in [('DAILY','../../secret'),('DAILY','20261111'),('DAILY','2026-02-30'),('../../secret','2026-11-11')]:
   with self.subTest(kind=kind,day=day),self.assertRaises((ValueError,TypeError)):
    report_filename(dict(report_type=kind,report_date=day))
