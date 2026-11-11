import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as V
import unittest
from unittest.mock import AsyncMock, Mock, patch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize
from reporting.incident_telegram import verify_owner_private
from ops.cloud.secretary_rpc import poll
import test_notification_center as fixtures

CONFIG={**fixtures.CFG,'automatic_notification_policy':'publication-v2',
        'automatic_updates_to_group':True,'account_report_policy':'shared_group'}


def bot():
    return V(get_me=AsyncMock(return_value=V(id=CONFIG['bot_id'],username=CONFIG['bot_username'])),
        get_chat=AsyncMock(return_value=V(id=CONFIG['owner_user_id'],type='private')),
        get_webhook_info=AsyncMock(return_value=V(url='')),get_updates=AsyncMock(return_value=[]))


class InboxPublicationIdentityTests(unittest.TestCase):
    def test_publication_archive_policy_does_not_block_verified_private_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive);b=bot()
            result=asyncio.run(poll(archive,root,CONFIG,0,owned_bot=b,proof={}))
            self.assertEqual(result,{'received':0,'accepted':0})
            self.assertEqual(b.get_chat.await_args.args,(CONFIG['owner_user_id'],))
            b.get_updates.assert_awaited_once()

    def test_wrong_native_identity_chat_or_webhook_still_rejects(self):
        for case in ('bot','owner','group','webhook'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive);b=bot()
                if case=='bot':b.get_me.return_value=V(id=CONFIG['bot_id']+1,username=CONFIG['bot_username'])
                elif case=='owner':b.get_chat.return_value=V(id=CONFIG['owner_user_id']+1,type='private')
                elif case=='group':b.get_chat.return_value=V(id=CONFIG['owner_user_id'],type='group')
                else:b.get_webhook_info.return_value=V(url='https://receiver.invalid')
                with self.assertRaises(PermissionError):asyncio.run(poll(archive,root,CONFIG,0,owned_bot=b,proof={}))
                b.get_updates.assert_not_awaited()

    def test_local_observer_runs_when_telegram_poll_fails(self):
        from ops.cloud import secretary_inbox as inbox
        class ManagedBot:
            def __init__(self,**kw):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*exc):pass
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);root=home/'.local/state/openclaw';(root/'runtime').mkdir(parents=True)
            (root/'runtime/secretary-policy.json').write_text(json.dumps(dict(approved=True,receiver_owner='cloud',grants_trading_permission=False,armed_at=0)))
            cfg=home/'.config/openclaw/telegram.json';cfg.parent.mkdir(parents=True);cfg.write_text(json.dumps(CONFIG));cfg.chmod(0o600)
            stopped=threading.Event()
            async def stop_sleep(*args):stopped.set()
            observer=Mock(return_value={'capacity':True})
            with patch.object(inbox.Path,'home',return_value=home),patch.object(inbox.threading,'Event',return_value=stopped),patch.object(inbox.signal,'signal'),patch.object(inbox,'monitoring_service',return_value=nullcontext()),patch('telegram.Bot',ManagedBot),patch.object(inbox,'poll',AsyncMock(side_effect=PermissionError)),patch.object(inbox,'observe',observer),patch.object(inbox.asyncio,'sleep',stop_sleep):
                asyncio.run(inbox.run_worker())
            observer.assert_called_once()
