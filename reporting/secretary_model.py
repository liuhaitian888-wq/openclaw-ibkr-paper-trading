"""One bounded Codex inference. Auth stays in CODEX_HOME; no model tools enabled."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

DISABLED=('shell_tool','unified_exec','multi_agent','plugins','hooks','in_app_browser','image_generation','view_image','in_app_chat','skill_search','tool_suggest','sleep_tool')


def analyze(prompt, *, codex, codex_home, empty_dir, model='gpt-6.1-sol', timeout=120):
    if model!='gpt-6.1-sol' or not 1<=timeout<=120 or len(prompt)>60_000:
        raise ValueError('Bounded approved model request required')
    cmd=[codex,'-a','never','exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
         '-C',str(empty_dir),'--sandbox','read-only','-m',model,'-c','web_search="disabled"',
         '-c','model_reasoning_effort="low"','--json']
    for feature in DISABLED:cmd.extend(['--disable',feature])
    cmd.append('-')
    env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY')}
    env['CODEX_HOME']=str(codex_home)
    with tempfile.TemporaryFile(mode='w+b') as out, tempfile.TemporaryFile(mode='w+b') as err:
        p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,env=env,start_new_session=True)
        try:p.communicate(prompt.encode(),timeout=timeout)
        except BaseException:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=5)
            raise
        if out.tell()>1_000_000:raise RuntimeError('Inference output exceeds budget; reconcile UNKNOWN')
        out.seek(0);messages=[];usage=None
        for line in out:
            try:event=json.loads(line)
            except ValueError:continue
            item=event.get('item',{})
            if event.get('type')=='item.completed':
                if item.get('type')=='agent_message':messages.append(item.get('text',''))
                elif item.get('type') not in ('reasoning',):raise RuntimeError('Unexpected model tool event; reconcile UNKNOWN')
            if event.get('type')=='turn.completed':usage=event.get('usage')
        if p.returncode or not messages or usage is None:raise RuntimeError('Inference not acknowledged; reconcile UNKNOWN')
    text=messages[-1].strip()
    if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1])
    result=json.loads(text)
    if not isinstance(result,dict) or not isinstance(result.get('summary'),str) or len(result['summary'])>3300:
        raise ValueError('Structured public result required')
    requests=result.get('tools',[])
    if not isinstance(requests,list) or len(requests)>4 or any(not isinstance(x,dict) for x in requests):
        raise ValueError('At most four structured read-only tool requests per turn')
    return result,usage
