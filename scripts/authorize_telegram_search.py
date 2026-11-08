"""Human-run local authorization. Never called by the secretary or cloud worker."""
import asyncio,getpass,json,logging,os,tempfile
from pathlib import Path

async def authorize(target,path):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    print('This creates a Telegram USER session, whose credential is not server-enforced read-only.')
    print('The search adapter only reads der bot messages; initialization locates der using up to 500 dialog metadata entries. No other chat content is fetched.')
    print('Credentials stay in the local mode0600 file, never in the model or cloud. Do not paste passwords, OTPs or sessions into chat.')
    if input('Type AUTHORIZE DER SEARCH to proceed: ')!='AUTHORIZE DER SEARCH':raise SystemExit('No authorization created')
    api_id=int(input('Telegram API ID (from my.telegram.org): '));api_hash=getpass.getpass('Telegram API hash: ')
    client=TelegramClient(StringSession(),api_id,api_hash,receive_updates=False,auto_reconnect=False,connection_retries=0,request_retries=0,flood_sleep_threshold=0)
    try:
        await client.start(phone=lambda:input('Telegram phone (local only): '),password=lambda:getpass.getpass('Telegram 2FA password (local only): '))
        me=await client.get_me()
        if me.id!=target['owner_user_id'] or me.bot:raise PermissionError('Wrong owner; no search configuration written')
        peer=None
        async with asyncio.timeout(30):
            async for dialog in client.iter_dialogs(limit=500):
                if dialog.id==target['chat_id']:peer=dialog.entity;break
        if peer is None:raise PermissionError('Configured der group not found; no group joined')
        cfg=dict(approved=True,owner_user_id=me.id,chat_id=target['chat_id'],channel_access_hash=peer.access_hash,
                 api_id=api_id,api_hash=api_hash,session=client.session.save())
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.telegram-search-',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(cfg,f);f.flush();os.fsync(f.fileno())
            os.chmod(name,0o600);os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)
        print('Owner session configured locally. No secret printed. No message history copied.')
    finally:await asyncio.wait_for(client.disconnect(),timeout=5)


def main():
    os.umask(0o077);logging.disable(logging.CRITICAL)
    folder=Path.home()/'.config/openclaw';target=folder/'telegram-search-target.json'
    if target.is_symlink() or target.stat().st_mode&0o077 or target.stat().st_size>4096:raise PermissionError('Private reviewed search target required')
    asyncio.run(authorize(json.loads(target.read_text()),folder/'telegram-search.json'))

if __name__=='__main__':main()
