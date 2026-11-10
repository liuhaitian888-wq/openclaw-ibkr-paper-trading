"""Cloud-owned ChatGPT OAuth through the official Codex CLI; no token extraction/copy."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from .secretary_api import atomic,ModelAPIError
from .secretary_model import analyze as codex_analyze

CODEX='/opt/openclaw/tools/codex/0.167.0/codex'


def oauth_ready(directory):
    directory=Path(directory)
    if directory.is_symlink() or directory.stat().st_mode&0o077:raise PermissionError('Private cloud OAuth home required')
    fd=os.open(directory/'auth.json',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode&0o077 or meta.st_size>65536 or meta.st_uid!=os.geteuid():
            raise PermissionError('Private owned OAuth cache required')
        data=json.loads(os.read(fd,65537))
    finally:os.close(fd)
    if data.get('auth_mode')!='chatgpt':raise PermissionError('ChatGPT OAuth login required; no API-key fallback')
    # Only the official CLI reads/refreshes token fields. Never return or log them.
    return True


def analyze(prompt,*,key_path,receipt_path,model='gpt-6.1-sol',**unused):
    oauth_ready(key_path)
    if model!='gpt-6.1-sol' or not isinstance(prompt,str) or not 0<len(prompt)<=60000:raise ValueError('Bounded approved OAuth model request required')
    receipt_path=Path(receipt_path)
    if receipt_path.exists() or receipt_path.with_suffix('.tmp').exists():raise ModelAPIError('EXISTING_OAUTH_ATTEMPT_NO_REPLAY')
    request_hash=hashlib.sha256(json.dumps({'input':prompt,'model':model,'effort':'low','provider':'codex_oauth'},sort_keys=True).encode()).hexdigest()
    atomic(receipt_path,{'state':'STARTED','request_sha256':request_hash,'provider':'codex_oauth','model':model,'reasoning_effort':'low','started_at':time.time()})
    empty=Path(key_path).parent/'secretary-oauth-empty'
    if not empty.is_dir() or any(empty.iterdir()):raise PermissionError('Empty cloud inference workspace required')
    try:
        result,usage=codex_analyze(prompt,codex=CODEX,codex_home=key_path,empty_dir=empty,model=model,force_chatgpt=True,timeout=unused.get('timeout',120))
        atomic(receipt_path,{'state':'ACKNOWLEDGED','request_sha256':request_hash,'provider':'codex_oauth','model':model,
            'reasoning_effort':'low','result':result,'usage':usage,'finished_at':time.time()})
        return result,usage
    except BaseException as exc:
        atomic(receipt_path,{'state':'UNKNOWN','request_sha256':request_hash,'provider':'codex_oauth','error_type':type(exc).__name__,'finished_at':time.time()})
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        raise ModelAPIError('OAUTH_'+type(exc).__name__) from None
