"""Protocol-specific acknowledgement; IDs are never synthesized."""
import json
from scripts.send_feishu_report import validate_feishu_response

SUCCESS_STATES = frozenset({'SENT', 'SENT_ACCEPTED', 'SENT_CONFIRMED'})


def classify(response, transport):
    if transport not in ('custom_webhook', 'app_message_api'):
        raise ValueError('Unsupported report transport')
    validate_feishu_response(response, context='report acknowledgement')
    payload = json.loads(response)
    data = payload.get('data', {})
    if not isinstance(data, dict):
        raise RuntimeError('Malformed message response data')
    message_id = data.get('message_id')
    valid_id = isinstance(message_id, str) and message_id.startswith('om_') and len(message_id) > 3
    if transport == 'app_message_api' and not valid_id:
        raise RuntimeError('Application API success lacks valid message_id')
    return {'status': 'SENT_CONFIRMED' if valid_id else 'SENT_ACCEPTED',
            'message_id': message_id if valid_id else None,
            'message_business_success': True, 'transport': transport}
