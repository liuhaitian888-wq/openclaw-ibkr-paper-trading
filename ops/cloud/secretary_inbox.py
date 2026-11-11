"""Single cloud Telegram input owner; deterministic controls never wait on a model."""
import asyncio,json,os,signal,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from ops.cloud.secretary_rpc import poll
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize
from reporting.secretary_controls import process_controls,tick_login
from reporting.secretary_observations import observe


async def run_worker():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    policy=json.loads((root/'runtime/secretary-policy.json').read_text())
    if policy.get('approved') is not True or policy.get('receiver_owner')!='cloud' or policy.get('grants_trading_permission') is not False:raise PermissionError('Approved cloud inbox ownership required')
    path=Path.home()/'.config/openclaw/telegram.json'
    if path.stat().st_mode&0o077:raise PermissionError('Private Telegram configuration required')
    config=json.loads(path.read_text());stopped=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopped.set())
    with monitoring_service('secretary-inbox',root):
        archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive)
        from telegram import Bot
        async with Bot(token=config['bot_token']) as bot:
            proof={};last_observation=0
            while not stopped.is_set():
                # Local observers have their own owner/budgets and do not depend
                # on Telegram polling or model/control availability.
                if time.monotonic()-last_observation>=60:
                    last_observation=time.monotonic()
                    try:print(json.dumps(observe(archive,root)),flush=True)
                    except Exception as exc:
                        print(json.dumps({'state':'OBSERVATION_UNAVAILABLE','error_type':type(exc).__name__,'at':time.time()}),flush=True)
                try:
                    result=await poll(archive,root,config,policy['armed_at'],owned_bot=bot,proof=proof)
                    process_controls(archive,root,config,policy)
                    from ops.cloud.secretary_control_executor import process_gateway_controls
                    process_gateway_controls(archive,root,config,policy)
                    tick_login(archive,root)
                    from reporting.secretary_live_status import tick as tick_status
                    tick_status(archive,root)
                    if result['accepted']:print(json.dumps({'accepted_native_owner_messages':result['accepted'],'at':time.time()}),flush=True)
                except Exception as exc:
                    print(json.dumps({'state':'INBOX_UNAVAILABLE','error_type':type(exc).__name__,'at':time.time()}),flush=True);await asyncio.sleep(5)
                await asyncio.sleep(.1)


def main():return asyncio.run(run_worker())


if __name__=='__main__':main()
