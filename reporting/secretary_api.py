"""Bounded OpenAI Responses transport; no retries, tool execution or raw error logs."""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import time

MODEL='gpt-6.1-sol'

class ModelAPIError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__('Model API outcome requires reconciliation: '+code)


def credential(path):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode&0o077 or meta.st_size>1024:
            raise PermissionError('Private bounded model credential required')
        value=os.read(fd,1025).decode().strip()
    finally:os.close(fd)
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,500}',value):raise PermissionError('Model credential format invalid')
    return value


def atomic(path,data):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        # Keep provenance, including an incomplete temporary file; never silently replay.
        raise


def response_text(data):
    if data.get('status')!='completed' or data.get('model')!=MODEL or not isinstance(data.get('id'),str):
        raise ModelAPIError('INCOMPLETE_OR_MODEL_MISMATCH')
    output=data.get('output')
    if not isinstance(output,list):raise ModelAPIError('OUTPUT_INVALID')
    messages=[]
    for item in output:
        if item.get('type')=='reasoning':continue  # Private reasoning is never stored or forwarded.
        if item.get('type')!='message' or item.get('role')!='assistant':raise ModelAPIError('UNEXPECTED_NATIVE_TOOL')
        for content in item.get('content',[]):
            if content.get('type')!='output_text' or not isinstance(content.get('text'),str):raise ModelAPIError('OUTPUT_INVALID')
            messages.append(content['text'])
    try:result=json.loads(''.join(messages))
    except (ValueError,TypeError):raise ModelAPIError('STRUCTURED_OUTPUT_INVALID') from None
    tools=result.get('tools',[]) if isinstance(result,dict) else None
    if (not isinstance(result,dict) or not isinstance(result.get('summary'),str) or not 0<len(result['summary'])<=3300
            or not isinstance(tools,list) or len(tools)>4 or any(not isinstance(x,dict) for x in tools)):
        raise ModelAPIError('STRUCTURED_OUTPUT_INVALID')
    return result


def analyze(prompt,*,key_path,receipt_path,model=MODEL,timeout=120,connection_factory=None,**unused):
    if model!=MODEL or not isinstance(prompt,str) or not 0<len(prompt)<=60_000 or not 1<=timeout<=120:
        raise ValueError('Bounded approved model request required')
    key=credential(key_path)
    receipt_path=Path(receipt_path)
    if receipt_path.exists() or receipt_path.with_suffix('.tmp').exists():raise ModelAPIError('EXISTING_ATTEMPT_NO_REPLAY')
    body=json.dumps({'model':MODEL,'reasoning':{'effort':'low'},'input':prompt,'store':False,
        'max_output_tokens':4096,'text':{'format':{'type':'json_object'}}},ensure_ascii=False).encode()
    request_hash=hashlib.sha256(body).hexdigest()
    atomic(receipt_path,{'state':'STARTED','request_sha256':request_hash,'started_at':time.time(),'model':MODEL,'reasoning_effort':'low'})
    connection_factory=connection_factory or (lambda:http.client.HTTPSConnection('api.openai.com',443,timeout=timeout,context=ssl.create_default_context()))
    try:
        with closing(connection_factory()) as conn:
            conn.request('POST','/v1/responses',body=body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            response=conn.getresponse()
            raw=response.read(1_000_001)
            if response.status!=200:raise ModelAPIError('HTTP_'+str(response.status))
            if len(raw)>1_000_000:raise ModelAPIError('RESPONSE_TOO_LARGE')
            try:data=json.loads(raw)
            except ValueError:raise ModelAPIError('RESPONSE_INVALID') from None
            result=response_text(data)
            usage=data.get('usage',{})
            if not isinstance(usage,dict):raise ModelAPIError('USAGE_INVALID')
            if key in json.dumps(result,ensure_ascii=False):raise ModelAPIError('CREDENTIAL_IN_OUTPUT')
            atomic(receipt_path,{'state':'ACKNOWLEDGED','request_sha256':request_hash,'response_id':data['id'],
                'model':MODEL,'reasoning_effort':'low','result':result,'usage':usage,'finished_at':time.time()})
            return result,usage
    except BaseException as exc:
        code=exc.code if isinstance(exc,ModelAPIError) else type(exc).__name__
        atomic(receipt_path,{'state':'UNKNOWN','request_sha256':request_hash,'error_code':code,'finished_at':time.time()})
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        raise ModelAPIError(code) from None
