"""Explicit capability probe: upload a synthetic PNG, NEVER send a message."""

import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from trading.production_paths import REPORT_ROOT
import hashlib
import json
import struct
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.send_feishu_report import load_env_file, upload_image



def main():
    env = Path('/Users/nbhsbgnb/Documents/New project/.secrets/feishu_image_upload.env')
    load_env_file(env)
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))
    png+=chunk(b'IDAT',zlib.compress((b'\x00'+b'\xee\xee\xee'*64)*64))+chunk(b'IEND',b'')
    evidence={'checked_at':datetime.now(timezone.utc).isoformat(),'source':str(env),
              'synthetic_image':True,'message_send_called':False}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'capability-probe.png';path.write_bytes(png)
        try:
            key=upload_image(path)
            evidence.update(upload_business_code=0,image_key_valid=key.startswith('img_'),
                            image_key_sha256=hashlib.sha256(key.encode()).hexdigest(),status='UPLOAD_VERIFIED')
        except Exception as exc:
            evidence.update(status='UPLOAD_UNVERIFIED',error_type=type(exc).__name__)
    output=REPORT_ROOT / 'incidents/2026-09-06-report-flood/upload-capability-probe.json'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))

if __name__ == '__main__':main()
