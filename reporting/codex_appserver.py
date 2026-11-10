"""One owned, bounded, tool-free native Codex turn. Never a Hosted Cloud client."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
import tomllib

from .secretary_model import DISABLED, CODE_MODE_DISABLED_NOTICE
from .secretary_oauth import CODEX, oauth_ready

EXTRA_DISABLED = ('apps', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
    'computer_use', 'code_mode_host', 'tool_call_mcp_elicitation', 'auth_elicitation',
    'skill_mcp_dependency_install', 'workspace_dependencies', 'daemon_auto_start',
    'unbounded_connection_retries', 'request_permissions_tool')
INSTRUCTIONS = ('You are the Hetzner Codex executor, not Hosted Codex Cloud. '
    'Analyze only the supplied registered-database diagnostic evidence. No native tools, '
    'shell, file access, network, code changes or deployment are authorized. '
    'Return JSON with one Chinese summary string (max 1600 characters). '
    'Do not invent data or turn historical timestamps into current broker health.')
SCHEMA = {'type': 'object', 'properties': {'summary': {'type': 'string'}},
          'required': ['summary'], 'additionalProperties': False}


def preflight(home):
    oauth_ready(home)
    config = Path(home) / 'config.toml'
    if config.is_symlink():
        raise PermissionError('OAuth configuration symlink refused')
    value = tomllib.loads(config.read_text()) if config.exists() else {}
    if any(k not in ('cli_auth_credentials_store', 'forced_login_method') for k in value):
        raise PermissionError('Dedicated OAuth home must contain no tool/provider/project configuration')
    if value.get('forced_login_method', 'chatgpt') != 'chatgpt' or value.get('cli_auth_credentials_store', 'file') != 'file':
        raise PermissionError('Dedicated file-backed ChatGPT OAuth required')


def argv(codex):
    cmd = [str(codex), '-a', 'never', 'app-server', '--listen', 'stdio://']
    config = {'forced_login_method': 'chatgpt', 'cli_auth_credentials_store': 'file',
        'web_search': 'disabled', 'project_doc_max_bytes': 0, 'model_reasoning_effort': 'low',
        'model_provider': 'secretary_oauth', 'model_providers.secretary_oauth.name': 'ChatGPT OAuth',
        'model_providers.secretary_oauth.requires_openai_auth': True,
        'model_providers.secretary_oauth.wire_api': 'responses',
        'model_providers.secretary_oauth.request_max_retries': 0,
        'model_providers.secretary_oauth.stream_max_retries': 0}
    for key, value in config.items():
        cmd.extend(['-c', key + '=' + json.dumps(value)])
    for name in (*DISABLED, *EXTRA_DISABLED):
        cmd.extend(['--disable', name])
    cmd.extend(['--enable', 'skip_host_skill_discovery'])
    return cmd


@contextmanager
def channel(cmd, home, cwd, timeout):
    """No reader threads or detached children. Both pipe directions have one deadline."""
    env = {k: v for k, v in os.environ.items() if k not in
           ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN')}
    env['CODEX_HOME'] = str(home)
    with tempfile.TemporaryFile() as err, selectors.DefaultSelector() as selector:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=err, start_new_session=True)
        os.set_blocking(p.stdout.fileno(), False)
        os.set_blocking(p.stdin.fileno(), False)
        deadline = time.monotonic() + timeout
        selector.register(p.stdout, selectors.EVENT_READ)
        pending = bytearray(); buffer = bytearray(); total = 0

        def send(value):
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
            if len(encoded) + len(pending) > 60000:
                raise ValueError('Bounded single RPC write required')
            registered = bool(pending)
            pending.extend(encoded)
            if not registered:
                selector.register(p.stdin, selectors.EVENT_WRITE)

        def receive():
            nonlocal total
            while True:
                # Flush a pending request even if a notification was already buffered.
                if not pending and b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n'); buffer[:] = rest
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('Native RPC object required')
                    return message
                left = deadline - time.monotonic()
                if left <= 0 or os.fstat(err.fileno()).st_size > 1_000_000:
                    raise TimeoutError('Native turn deadline/output budget exceeded')
                events = selector.select(min(left, .2))
                for key, mask in events:
                    if mask & selectors.EVENT_WRITE:
                        n = os.write(p.stdin.fileno(), pending); del pending[:n]
                        if not pending:
                            selector.unregister(p.stdin)
                    if mask & selectors.EVENT_READ:
                        chunk = os.read(p.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError('Native process closed before acknowledgement')
                        total += len(chunk); buffer.extend(chunk)
                        if total > 1_000_000:
                            raise ValueError('Native output exceeds budget')
        try:
            yield send, receive
        finally:
            p.stdin.close(); p.stdout.close()
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=2)
            else:
                p.wait()


def run(evidence, *, home, empty_dir, record, codex=CODEX, timeout=120, handshake_only=False, probe_thread_only=False):
    """record persists each native checkpoint before another side effect is sent."""
    if not 1 <= timeout <= 120:
        raise ValueError('Bounded native timeout required')
    if probe_thread_only:
        if Path(home).is_symlink() or not Path(home).is_dir() or any(Path(home).iterdir()):
            raise PermissionError('Protocol probe uses an empty credential-free home')
    else:
        preflight(home)
    empty_dir = Path(empty_dir)
    if empty_dir.is_symlink() or not empty_dir.is_dir() or any(empty_dir.iterdir()):
        raise PermissionError('Dedicated empty inference directory required')
    prompt = json.dumps({'scope': 'registered-db-diagnostic-v1', 'evidence': evidence},
                        ensure_ascii=False, allow_nan=False)
    if len(prompt.encode()) > 45000:
        raise ValueError('Bounded diagnostic evidence required')
    with channel(argv(codex), home, empty_dir, timeout) as (send, receive):
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {
            'name': 'buy_der_restricted_engineering', 'title': 'Hetzner Codex执行器', 'version': '1'}}})

        deferred = []
        def response(identity):
            for _ in range(1000):
                message = receive()
                if 'method' in message and 'id' in message:
                    raise PermissionError('Native tool/approval request refused')
                if message.get('id') == identity:
                    if 'error' in message or not isinstance(message.get('result'), dict):
                        raise RuntimeError('Native RPC rejected')
                    return message['result']
                deferred.append(message)
            raise ValueError('Native event budget exceeded')

        response(1)
        send({'method': 'initialized', 'params': {}})
        if handshake_only:
            # The initialize result proves the protocol entry, without account/turn access.
            return {'state': 'INITIALIZE_ACKNOWLEDGED', 'inference': False}
        send({'id': 2, 'method': 'thread/start', 'params': {
            'model': 'gpt-6.1-sol', 'modelProvider': 'secretary_oauth',
            'cwd': str(empty_dir), 'approvalPolicy': 'never', 'sandbox': 'read-only',
            'baseInstructions': INSTRUCTIONS, 'developerInstructions': INSTRUCTIONS,
            'ephemeral': True, 'serviceName': 'buy_der_restricted_engineering'}})
        created = response(2)
        if (created.get('model') != 'gpt-6.1-sol' or created.get('modelProvider') != 'secretary_oauth'
                or created.get('approvalPolicy') != 'never'
                or created.get('sandbox') != {'type': 'readOnly', 'networkAccess': False}):
            raise PermissionError('Native model/provider/permission configuration mismatch')
        thread = created['thread']['id']
        if not isinstance(thread, str) or not 1 <= len(thread) <= 160:
            raise ValueError('Exact native thread identity required')
        record('THREAD_CREATED', {'thread_id': thread})
        if probe_thread_only:
            return {'state': 'THREAD_CREATED_NO_TURN', 'thread_id': thread, 'inference': False}
        send({'id': 3, 'method': 'turn/start', 'params': {
            'threadId': thread, 'input': [{'type': 'text', 'text': prompt}],
            'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
            'effort': 'low', 'outputSchema': SCHEMA}})
        turn = response(3)['turn']
        identity = turn['id']
        if not isinstance(identity, str) or not 1 <= len(identity) <= 160 or turn.get('status') != 'inProgress':
            raise ValueError('Exact native accepted turn identity required')
        native = {'thread_id': thread, 'turn_id': identity}
        record('TURN_ACCEPTED', native)
        texts = []; notice = False
        for _ in range(5000):
            message = deferred.pop(0) if deferred else receive()
            if 'method' in message and 'id' in message:
                raise PermissionError('Native tool/approval request refused')
            method = message.get('method'); params = message.get('params', {})
            if method == 'error':
                if not notice and params.get('error', {}).get('message') == CODE_MODE_DISABLED_NOTICE:
                    notice = True; continue
                raise RuntimeError('Native inference error')
            if method in ('item/started', 'item/completed'):
                item = params.get('item', {})
                if item.get('type') not in ('agentMessage', 'reasoning'):
                    raise PermissionError('Unexpected native tool event refused')
                if params.get('threadId') != thread or params.get('turnId') != identity:
                    raise ValueError('Native item identity mismatch')
                if method == 'item/completed' and item.get('type') == 'agentMessage':
                    texts.append(item.get('text', ''))
            if method == 'turn/completed':
                completed = params.get('turn', {})
                if params.get('threadId') != thread or completed.get('id') != identity:
                    raise ValueError('Native completion identity mismatch')
                if completed.get('status') != 'completed' or not texts:
                    raise RuntimeError('Native turn did not complete successfully')
                value = json.loads(texts[-1])
                if set(value) != {'summary'} or not isinstance(value['summary'], str) or not 1 <= len(value['summary']) <= 1600:
                    raise ValueError('Bounded public native result required')
                result = {**native, 'status': 'completed', 'summary': value['summary']}
                record('TURN_COMPLETED', result)
                return result
        raise ValueError('Native event budget exceeded')
