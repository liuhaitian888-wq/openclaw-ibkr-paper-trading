"""Read-only per-stage native message/notification timing. Never prints message text."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reporting.secretary_queue import latency_sample


def samples(root,limit=30):
    with closing(sqlite3.connect((root/'agent_secretary.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
        rows=c.execute("""SELECT e.occurrence,e.kind,e.recorded_at,r.occurrence,r.started_at,v.recorded_at,p.received_at
            FROM secretary_events e JOIN secretary_received p ON p.instruction=e.occurrence
            LEFT JOIN secretary_runs r ON r.instruction=e.occurrence
            LEFT JOIN secretary_events v ON v.occurrence=r.result_event
            WHERE e.origin='USER' ORDER BY e.rowid DESC LIMIT ?""",(limit,)).fetchall()
        model=[dict(kind=k,run=p,at=t,data=json.loads(d)) for k,p,t,d in c.execute("SELECT kind,parent,recorded_at,payload FROM secretary_events WHERE kind IN ('MODEL_STARTED','MODEL_FINISHED') ORDER BY rowid DESC LIMIT 30")]
    output=[]
    with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
        for instruction,kind,saved,run,claimed,finished,received in rows:
            for label,key in [('ack','secretary-ack:'+instruction),('result','secretary:'+str(run))]:
                row=c.execute('''SELECT n.id,n.status,d.attempt_started_at,d.ack_received_at
                    FROM notification_outbox n LEFT JOIN notification_delivery d ON d.notification_id=n.id
                    WHERE n.incident_key=?''',(key,)).fetchone()
                if row:
                    output.append(dict(instruction=instruction,kind=kind,response=label,outbox=row[0],status=row[1],
                        timing=latency_sample(received,saved,claimed if label=='result' else saved,finished if label=='result' else saved,row[2],row[3])))
    return {'samples':output,'model_calls':model,'timestamp_precision':'server arrival; native Telegram dates have whole-second precision'}


if __name__=='__main__':print(json.dumps(samples(Path.home()/'.local/state/openclaw'),ensure_ascii=False,indent=2))
