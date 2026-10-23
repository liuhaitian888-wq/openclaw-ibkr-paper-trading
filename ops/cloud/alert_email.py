"""Separate opt-in SMTP notification worker; never changes execution permissions."""
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import smtplib
import ssl
import time


def main():
    os.umask(0o077)
    root = Path.home()/'.local/state/openclaw'
    runtime = root/'runtime'
    config = Path.home()/'.config/openclaw/smtp.json'
    if not config.is_file() or not (runtime/'EMAIL_ALERTS_ARMED').is_file():
        print('EMAIL_NOT_CONFIGURED_OR_ARMED')
        return
    if config.stat().st_mode & 0o077:
        raise PermissionError('SMTP configuration must be mode 0600')
    cfg = json.loads(config.read_text())
    status = json.loads((runtime/'cloud-status.json').read_text())
    age = time.time()-datetime.fromisoformat(status['observed_at']).timestamp()
    smoke = status['smoke']
    summary = dict(overall=smoke['overall'], checks=smoke['checks'],
                   services=status['services'], stale_status=age < 0 or age > 600,
                   low_disk=status['disk_free_fraction'] < .20)
    signature = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
    ledger_path = runtime/'email-alert-ledger.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.is_file() else {}
    if ledger.get('signature') == signature and ledger.get('status') in ('STARTED', 'UNKNOWN'):
        print('Ambiguous SMTP outcome requires manual review; no automatic replay')
        return
    if ledger.get('signature') == signature and time.time()-ledger.get('sent_at', 0) < 86400:
        return
    message = EmailMessage()
    message['From'] = cfg['sender']
    message['To'] = 'liuhaitian888@hotmail.com'
    message['Subject'] = '[IBKR Paper cloud] '+smoke['overall']
    message.set_content('Paper-only cloud status. Inspect the SSH-protected console.\n'
                        +json.dumps(summary, indent=2)+'\nNo orders were sent by this monitor.')
    def save(state):
        temporary = ledger_path.with_suffix('.tmp')
        with temporary.open('w') as handle:
            json.dump(dict(signature=signature, sent_at=time.time(), status=state), handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(ledger_path)
    save('STARTED')
    # Dedicated SMTP relay credentials only; never an IBKR or main mailbox password.
    try:
        with smtplib.SMTP(cfg['host'], int(cfg.get('port', 587)), timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(cfg['username'], cfg['relay_password'])
            smtp.send_message(message)
    except BaseException:
        save('UNKNOWN')
        raise
    # Ambiguous SMTP failures are not recorded as success. Delivery still needs
    # recipient confirmation; SMTP acceptance is not proof of inbox receipt.
    save('SMTP_ACCEPTED_NOT_DELIVERY_CONFIRMED')


if __name__ == '__main__':
    main()
