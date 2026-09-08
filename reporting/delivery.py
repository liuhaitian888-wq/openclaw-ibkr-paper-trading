"""Report-only transaction coordinator. UNKNOWN never auto-resends.

No network implementation is installed by this module. Production activation is
an explicit later acceptance gate; this candidate can exercise sandbox transports.
"""
import hashlib
import json
import struct
import zlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .errors import normalize,exception_error
from .generation import validation
from .ledger import Ledger,Busy,save

BJ=ZoneInfo('Asia/Shanghai')
SUCCESS={'SENT_ACCEPTED','SENT_CONFIRMED','SENT_SIMULATED'}
HOLD={'UNKNOWN','SENDING','ACCEPTED_PENDING_COMMIT'}|SUCCESS
MAX_ATTEMPTS=3
RETRY_INTERVAL=timedelta(minutes=30)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def valid_png(raw):
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):return False
    offset=8;seen=[]
    try:
        while offset<len(raw):
            length=struct.unpack('>I',raw[offset:offset+4])[0];tag=raw[offset+4:offset+8]
            data=raw[offset+8:offset+8+length];crc=struct.unpack('>I',raw[offset+8+length:offset+12+length])[0]
            if zlib.crc32(tag+data)&0xffffffff!=crc:return False
            if tag==b'IHDR' and (length!=13 or min(struct.unpack('>II',data[:8]))<=0):return False
            seen.append(tag);offset+=12+length
        return offset==len(raw) and seen[0]==b'IHDR' and seen[-1]==b'IEND' and b'IDAT' in seen
    except (struct.error,IndexError):return False


class Rejected(Exception):
    def __init__(self,response,http_status=200,auth=False):
        self.response=response;self.http_status=http_status;self.auth=auth
        super().__init__('Explicit provider rejection')

class Delivery:
    def __init__(self,state_dir,health,transport,*,sandbox=False,fault=None,archive_root=None):
        self.ledger=Ledger(state_dir);self.health=health;self.transport=transport
        self.archive_root=Path(archive_root) if archive_root else self.ledger.directory/'reports'/'pending'
        self.sandbox=sandbox;self.fault=fault or (lambda stage:None)
    def _checkpoint(self,name):self.fault(name)
    def _block(self,code,now,raw=None):return {'status':'BLOCKED','error':normalize(code,raw=raw,now=now)}
    def _artifact(self,m,now):
        if not m.get('report_id') or m.get('report_type') not in ('DAILY','WEEKLY','MONTHLY'):
            return self._block('REPORT-DATE-001',now)
        if m.get('simulation') and not self.sandbox:return self._block('REPORT-MOCK-001',now)
        try:
            path=Path(m['artifact_path']);raw=path.read_bytes()
            if not valid_png(raw):return self._block('REPORT-GEN-001',now,{'reason':'Invalid PNG'})
            if sha(path)!=m['artifact_hash'] or sha(m['source_json'])!=m['source_hash']:
                return self._block('REPORT-HASH-001',now)
            report=json.loads(Path(m['source_json']).read_text())
            period=report['trading_period']
            identity=f"{report['report_type'].lower()}:{period['start_date']}:{period['end_date_exclusive']}"
            if identity!=m['report_id'] or report['report_date']!=m['report_date'] or period!=m['trading_session']:
                return self._block('REPORT-DATE-001',now)
            if report.get('simulation') and not self.sandbox:return self._block('REPORT-MOCK-001',now)
            if m['report_date']>now.date().isoformat():return self._block('REPORT-DATE-001',now)
            check=validation(report,now)
            if not check['ready']:return {'status':'BLOCKED','error':check['issues'][0],'validation':check}
        except (OSError,KeyError,ValueError,TypeError) as exc:
            return self._block('REPORT-GEN-001',now,{'exception_type':type(exc).__name__,'raw_message':str(exc)})
        return None
    def _archive(self,state,m,now):
        # One canonical pending directory, preserving bytes and full metadata.
        key=m['report_id'];previous=state['reports'].get(key,{})
        if previous.get('status') in SUCCESS:return {'status':'DUPLICATE','record':previous}
        folder=self.archive_root/hashlib.sha256(key.encode()).hexdigest()[:24]
        folder.mkdir(parents=True,exist_ok=True)
        path=Path(m['artifact_path'])
        if path.exists() and not (folder/'report.png').exists():(folder/'report.png').write_bytes(path.read_bytes())
        record={**previous,'report_id':key,'manifest':m,'status':('UNKNOWN' if previous.get('status') in ('UNKNOWN','SENDING','ACCEPTED_PENDING_COMMIT') else 'ARCHIVED_UNSENT'),
                'reason':'Cross-day unsent; explicit authorization required','archived_at':now.isoformat(),'archive_path':str(folder),'requires_review':True}
        if (folder/'report.png').exists():
            record['archived_artifact_hash']=sha(folder/'report.png')
            if record['archived_artifact_hash']!=m.get('artifact_hash'):
                record['archive_error']=normalize('REPORT-HASH-001',raw={'reason':'Artifact mutated before archive'},now=now)
        source=Path(m.get('source_json',''))
        if source.is_file() and not (folder/'source.json').exists():(folder/'source.json').write_bytes(source.read_bytes())
        state['reports'][key]=record;save(folder/'metadata.json',record);self.ledger.commit(state)
        return {'status':record['status'],'archive_path':str(folder)}
    def attempt(self,manifest,now,*,approved_hash,trigger='manual'):
        if now.tzinfo is None:raise ValueError('Timezone-aware clock required')
        now=now.astimezone(BJ)
        if not self.sandbox:
            # Intentionally not deployable from a development worktree this round.
            return self._block('DELIVERY-PAUSED-001',now,{'reason':'Production acceptance not granted'})
        if getattr(self.transport,'sandbox',False) is not True:
            return self._block('REPORT-MOCK-001',now,{'reason':'Sandbox requires simulated transport'})
        try:
            with self.ledger.locked():return self._attempt(manifest,now,approved_hash,trigger)
        except Busy:return self._block('LEDGER-LOCK-001',now)
        except (OSError,ValueError) as exc:
            # Corrupt or unavailable ledger must never trigger an unrecorded POST.
            return self._block('LEDGER-COMMIT-001',now,{'exception_type':type(exc).__name__,'raw_message':str(exc)})
    def _attempt(self,m,now,approved_hash,trigger):
        if (self.ledger.directory/'PAUSED').exists():return self._block('DELIVERY-PAUSED-001',now)
        try:
            if trigger not in ('manual','scheduler','recovery'):return self._block('SCHED-AUTHORITY-001',now)
            for field in ('report_id','report_date','artifact_path','artifact_hash','source_json','source_hash'):
                if not isinstance(m.get(field),str) or not m[field]:raise ValueError('Missing manifest field '+field)
            datetime.strptime(m['report_date'],'%Y-%m-%d')
        except (ValueError,AttributeError) as exc:return self._block('REPORT-DATE-001',now,{'reason':str(exc)})
        state=self.ledger.read();key=m.get('report_id');old=state['reports'].get(key)
        for record in state['reports'].values():
            if record['status'] in ('SENDING','ACCEPTED_PENDING_COMMIT'):
                record.update(status='UNKNOWN',requires_review=True,error=normalize('DELIVERY-UNKNOWN-001',raw={'reason':'Process terminated before durable acknowledgement'},now=now))
        self.ledger.commit(state)
        if m.get('report_date','')<now.date().isoformat():return self._archive(state,m,now)
        if old and old['status'] in HOLD:return {'status':'DUPLICATE','record':old}
        if any(k!=key and v.get('report_date')==m.get('report_date') and v.get('attempts',0)>0 for k,v in state['reports'].items()):
            return self._block('SCHED-AUTHORITY-001',now,{'reason':'Another report already owns this dispatch date; no lower-tier fallback'})
        if old and old.get('manifest',{}).get('artifact_hash')!=m.get('artifact_hash'):return self._block('REPORT-HASH-001',now)
        if approved_hash!=m.get('artifact_hash'):return self._block('REPORT-HASH-001',now)
        if old and old.get('attempts',0)>=MAX_ATTEMPTS:return {'status':'RETRY_EXHAUSTED'}
        if old and old.get('attempts',0):
            if old.get('error',{}).get('retryable')=='no':return {'status':'NON_RETRYABLE','error':old['error']}
            if now<datetime.fromisoformat(old['attempted_at'])+RETRY_INTERVAL:return {'status':'RETRY_NOT_DUE'}
        blocked=self._artifact(m,now)
        if blocked:
            self.ledger.incident(state,key,blocked['error'],now);self.ledger.commit(state);return blocked
        # Durable storage probe and full dependency probe before every attempt.
        self._checkpoint('disk_probe');self.ledger.event(state,'PREFLIGHT_STARTED',now,report_id=key);self.ledger.commit(state)
        preflight=self.health.preflight(now)
        failed=next((h for h in preflight if h['state']!='HEALTHY'),None)
        if failed:
            result={'status':'BLOCKED','error':failed.get('error') or normalize('RECOVERY-PREFLIGHT-001',raw=failed,now=now)}
            self.ledger.incident(state,key,result['error'],now);self.ledger.commit(state);return result
        self._checkpoint('after_preflight')
        blocked=self._artifact(m,now)  # Detect mutations while preflight ran.
        if blocked:return blocked
        attempts=(old or {}).get('attempts',0)+1
        record={'report_id':key,'report_date':m['report_date'],'manifest':m,'artifact_hash':m['artifact_hash'],'artifact_path':m['artifact_path'],
                'status':'UPLOADING','attempts':attempts,'attempted_at':now.isoformat(),'created_at':(old or {}).get('created_at',now.isoformat()),
                'sent_at':None,'trigger_source':trigger,'history':(old or {}).get('history',[]),'namespace':'sandbox'}
        state['reports'][key]=record;self.ledger.commit(state)
        phase='upload'
        try:
            self._checkpoint('before_upload');image_key=self.transport.upload(Path(m['artifact_path']))
            if not isinstance(image_key,str) or not image_key.startswith('img_'):raise Rejected({'code':'INVALID_IMAGE_KEY','msg':'Upload missing image key'})
            record['image_upload_result']={'accepted':True,'image_key_valid':True}
            self.ledger.event(state,'IMAGE_UPLOAD_ACCEPTED',now,report_id=key)
            blocked=self._artifact(m,now)
            if blocked:
                record.update(status='FAILED',error=blocked['error']);self.ledger.commit(state);return blocked
            record['status']='SENDING';self.ledger.commit(state)
            phase='send';self._checkpoint('before_send');response=self.transport.send(image_key)
            raw=response if isinstance(response,dict) else json.loads(response)
            if not isinstance(raw,dict):raise ValueError('Malformed response')
            codes=[raw[k] for k in ('code','StatusCode') if k in raw]
            if not codes or any(type(c) is not int for c in codes):raise ValueError('Unrecognized acknowledgement')
            if any(c!=0 for c in codes):raise Rejected(raw)
            # Remote acceptance and local commit are separate events.
            phase='commit';record.update(status='ACCEPTED_PENDING_COMMIT',raw_response=raw,remote_accepted_at=now.isoformat())
            self.ledger.event(state,'REMOTE_ACCEPTED',now,report_id=key,raw_response=raw)
            self._checkpoint('before_commit')
            record.update(status='SENT_SIMULATED',sent_at=now.isoformat())
            record['history'].append({'attempt':attempts,'status':record['status'],'timestamp':now.isoformat()})
            self.ledger.event(state,'WRITE_SENT_ACCEPTED',now,report_id=key,namespace='sandbox')
            self.ledger.commit(state);self._checkpoint('after_commit')
            verified=self.ledger.read()['reports'][key]
            if verified['status']!='SENT_SIMULATED':raise OSError('Verification failed')
            return {'status':'SENT_SIMULATED','upload_success':True,'image_key_valid':True,'protocol_success':True,'ledger_commit_success':True,'ledger_verify_success':True}
        except Exception as exc:
            raw={'exception_type':type(exc).__name__,'raw_message':str(exc),'request_context':{'stage':phase,'report_id':key}}
            if isinstance(exc,Rejected):
                code='FEISHU-AUTH-001' if exc.auth or exc.http_status in (401,403) else 'FEISHU-UPLOAD-001' if phase=='upload' else 'FEISHU-SEND-001'
                raw.update(http_status=exc.http_status,raw_response_body=exc.response)
                error=normalize(code,raw=raw,now=now);status='FAILED'
            elif phase=='upload':error=exception_error(exc,stage=phase,now=now);status='FAILED'
            else:error=normalize('LEDGER-COMMIT-001' if phase=='commit' else 'DELIVERY-UNKNOWN-001',raw=raw,now=now);status='UNKNOWN'
            record.update(status=status,error=error,requires_review=status=='UNKNOWN')
            record['history'].append({'attempt':attempts,'status':status,'timestamp':now.isoformat(),'error':error})
            self.ledger.incident(state,key,error,now)
            try:self.ledger.commit(state)
            except OSError:pass  # durable SENDING holds next process; cannot resend
            return {'status':status,'error':error,'remote_accepted':phase=='commit'}
