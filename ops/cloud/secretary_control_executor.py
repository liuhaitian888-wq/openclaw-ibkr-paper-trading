"""Fixed native-owner Gateway start in the existing inbox; no model or Mac dependency."""
from contextlib import closing
import json
import math
import subprocess
from ops.cloud.gateway_watchdog import require_service_user
from reporting.secretary_controls import pending_controls,finish_start
from reporting.secretary_queue import CONVERSATION

UNIT='ibkr-gateway.service'


def process_gateway_controls(archive,root,config,policy,*,run_command=None):
    if (policy.get('approved') is not True or policy.get('receiver_owner')!='cloud'
            or policy.get('grants_trading_permission') is not False
            or policy.get('gateway_start_assistance_approved') is not True
            or policy.get('gateway_start_control_owner')!='cloud_inbox'):
        return {'state':'DISABLED','processed':0}
    since=policy.get('gateway_start_control_since')
    if type(since) not in (int,float) or not math.isfinite(since) or since<=0:
        raise PermissionError('Explicit fresh control-owner cutover required')
    require_service_user()
    invoke=run_command or subprocess.run;outcomes=[]
    controls=pending_controls(archive,kinds=('GATEWAY_START_REQUESTED',),after=since,owner='cloud_inbox',limit=1)
    for control in controls:
        run=control['run']
        with closing(archive.connect()) as c:
            row=c.execute('SELECT origin,kind,payload FROM secretary_events WHERE occurrence=?',(control['instruction'],)).fetchone()
        data=json.loads(row[2]) if row else {};parts=str(data.get('text','')).split()
        owner=config.get('owner_user_id');command=parts[0].split('@') if parts else []
        valid=(row is not None and row[:2]==('USER','CONTROL_INSTRUCTION')
            and data.get('source')=='Telegram native owner message' and type(owner) is int
            and config.get('owner_private_verified') is True and config.get('owner_private_chat_id')==owner
            and data.get('chat_id')==owner and type(data.get('timestamp')) is int and data['timestamp']>=since
            and type(data.get('update_id')) is int and type(data.get('message_id')) is int
            and len(parts)==1 and command[0]=='/login_assist'
            and (len(command)==1 or len(command)==2 and command[1]==config.get('bot_username')))
        if not valid:
            outcomes.append(finish_start(archive,root,{'run':run,'not_attempted_reason':'原生owner指令或切换时间未核验'}));continue
        try:
            status=invoke(['/usr/bin/systemctl','show',UNIT,'-p','ActiveState','--value'],capture_output=True,text=True,timeout=3)
            state=status.stdout.strip() if status.returncode==0 else 'unavailable'
        except (OSError,subprocess.SubprocessError):state='unavailable'
        if state not in ('inactive','failed'):
            known=state in ('active','activating','reloading','deactivating')
            outcomes.append(finish_start(archive,root,{'run':run,'not_attempted_reason':'当前systemd状态 '+state+'；保持既有owner','already_running':known}));continue
        archive.append(run+':native-start',CONVERSATION,origin='SYSTEM',kind='GATEWAY_START_ATTEMPT',parent=control['instruction'],
            payload={'unit':UNIT,'verb':'start','state_before':state,'owner':'cloud_inbox','grants_trading_permission':False})
        try:
            accepted=invoke(['/usr/bin/systemctl','--no-ask-password','--no-block','start',UNIT],capture_output=True,timeout=5).returncode==0
        except (OSError,subprocess.SubprocessError):accepted=False
        outcomes.append(finish_start(archive,root,{'run':run,'accepted':accepted}))
    return {'state':'PROCESSED','processed':len(outcomes),'outcomes':outcomes}
