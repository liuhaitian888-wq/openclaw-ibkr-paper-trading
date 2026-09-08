"""Import evidence into report-only ledger; never mark error notifications as reports."""
import fcntl
import hashlib
import json
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.report_delivery_guard import STATE_DIR,save


def reconcile(log_path,state_dir=STATE_DIR):
    raw=log_path.read_bytes();rows=[];attempt_time=None
    for line in raw.decode().splitlines():
        if 'send: starting' in line:
            attempt_time=line.split(' ',1)[0]
        if not attempt_time or not attempt_time.startswith('2026-09-06') or not line.startswith('{'):continue
        try: result=json.loads(line)
        except ValueError:continue
        if result.get('status')!='image_failed':continue
        response=result.get('failure_notification_response')
        try:ack=json.loads(response) if response else {}
        except ValueError:ack={}
        delivered=(result.get('failure_notification_sent') is True and ack.get('code')==0)
        preflight=result.get('error')=='missing Feishu image upload credentials or FEISHU_IMAGE_KEY'
        rows.append({'report_type':'DAILY','trading_date':'UNKNOWN','logical_report_id':'UNKNOWN',
                     'content_hash':None,'attempt_number':len(rows)+1,'attempt_time':attempt_time,
                     'image_upload_result':{'status':'NOT_CALLED' if preflight else 'UNKNOWN'},
                     'webhook_result':{'message_kind':'failure_notification','status':'SENT_ACCEPTED' if delivered else 'UNKNOWN'},
                     'delivery_status':'BLOCKED_LOCAL_PREFLIGHT' if preflight else 'UNKNOWN',
                     'error_code':'MISSING_IMAGE_CREDENTIALS' if preflight else 'UNKNOWN','warning_status':'HISTORICAL_DUPLICATE_NOTIFICATIONS'})
        attempt_time=None
    evidence={'incident_id':'2026-09-06-report-flood','report_send_attempts':len(rows),
              'image_upload_attempts':0 if all(r['image_upload_result']['status']=='NOT_CALLED' for r in rows) else None,
              'complete_report_images_delivered':0 if all(r['delivery_status']=='BLOCKED_LOCAL_PREFLIGHT' for r in rows) else None,
              'failure_notifications_accepted':sum(r['webhook_result']['status']=='SENT_ACCEPTED' for r in rows),
              'classification':'failure/error notifications; not complete reports','source_log_sha256':hashlib.sha256(raw).hexdigest(),
              'records':rows,'warning':{'warning_id':'incident:2026-09-06-report-flood','local_only':True,'status':'REVIEWED_CONTAINED'}}
    if len(rows)!=290:raise RuntimeError('Historical count mismatch; do not import without review')
    state_dir.mkdir(parents=True,exist_ok=True)
    with (state_dir/'delivery.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=state_dir/'delivery.json';state=json.loads(path.read_text()) if path.exists() else {'reports':{}}
        state.setdefault('historical_incidents',{})[evidence['incident_id']]=evidence
        save(path,state)
    return {k:v for k,v in evidence.items() if k not in ('records','warning')}

if __name__=='__main__':
    print(json.dumps(reconcile(Path(__file__).resolve().parents[1]/'logs/daily_feishu_scheduler.log'),indent=2))
