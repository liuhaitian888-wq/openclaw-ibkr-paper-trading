"""Response style and bounded conversation context; never grants tool permissions."""
from contextlib import closing
import json
from .errors import redact

MODES = ('CHAT', 'TASK', 'RESEARCH')
COMMANDS = {'/chat': 'CHAT', '/task': 'TASK', '/research': 'RESEARCH', '/secretary': 'AUTO'}


def preference(payload):
    if payload.get('autonomous') is True:
        return 'RESEARCH'
    first = (payload.get('text', '').split() or [''])[0].split('@')[0]
    return COMMANDS.get(first, 'AUTO')


def response_mode(payload, result):
    forced = preference(payload)
    if forced != 'AUTO':
        return forced
    mode = result.get('response_mode', 'CHAT')
    return mode if mode in MODES else 'CHAT'


def recent_context(archive, instruction, payload):
    # Only earlier completed owner exchanges from the exact same native chat.
    if type(payload.get('chat_id')) is not int:
        return []
    with closing(archive.connect()) as c:
        rows = c.execute("""SELECT e.payload, answer.payload FROM secretary_events e
            JOIN secretary_runs r ON r.instruction=e.occurrence
            JOIN secretary_events answer ON answer.occurrence=r.result_event
            WHERE e.origin='USER' AND e.kind='CHAT_INSTRUCTION' AND r.state='SUCCEEDED'
            AND e.rowid<(SELECT rowid FROM secretary_events WHERE occurrence=?)
            AND e.recorded_at>=(SELECT recorded_at-86400 FROM secretary_events WHERE occurrence=?)
            ORDER BY e.rowid DESC LIMIT 30""", (instruction, instruction)).fetchall()
    result = []
    for question, answer in rows:
        q, a = json.loads(question), json.loads(answer)
        if q.get('chat_id') != payload['chat_id']:
            continue
        result.append({'user': redact(str(q.get('text', ''))[:800]),
                       'assistant': redact(str(a.get('summary', ''))[:1200])})
        if len(result) == 4:
            break
    return list(reversed(result))
