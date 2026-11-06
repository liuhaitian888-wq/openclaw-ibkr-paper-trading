"""Telegram report and operational notification delivery with durable no-replay ownership."""
from datetime import timezone
import asyncio
import hashlib
import logging
from pathlib import Path
import re
import time


def validate_config(config):
    if (not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{25,}',config.get('bot_token',''))
            or config.get('bot_username')!='deehub_paper_reports_bot'
            or type(config.get('chat_id')) is not int or config['chat_id']>=0
            or config.get('expected_group_title')!='der'
            or config.get('expected_member_count')!=2 or config.get('target_verified') is not True
            or type(config.get('owner_user_id')) is not int):
        raise PermissionError('Verified private der report target required')


def report_bytes(item,root):
    if item['kind'] not in ('REPORT_BUNDLE','REPORT_SUPPLEMENT'):
        return []
    artifacts=item['payload'].get('png_artifacts',[])
    if len(artifacts)>3:raise ValueError('At most three report PNGs permitted')
    if not artifacts and item['payload'].get('included_reports'):
        raise ValueError('Included reports require original PNGs')
    result=[]
    for artifact in artifacts:
        path=Path(artifact['path']).resolve();path.relative_to(Path(root).resolve())
        if path.suffix!='.png' or not 0<path.stat().st_size<=10*1024*1024:
            raise ValueError('Bounded original PNG required')
        data=path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=artifact['sha256']:
            raise ValueError('Report content differs from manifest')
        result.append((path.name,data))
    return result


from .notification_text import notification_text


async def send_one(store,coordinator,config,*,report_root,claimed_item=None,bot_factory=None,clock=time.time):
    validate_config(config)
    item=claimed_item if claimed_item is not None else store.claim()
    if item is None:return 'BLOCKED_UNKNOWN' if store.uncertain_notifications() else 'EMPTY'
    operation='notification:outbox:'+str(item['id'])
    # Never log HTTP URLs: Telegram embeds credentials in their path.
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    if bot_factory is None:
        from telegram import Bot
        bot_factory=Bot
    started=False
    try:
        documents=report_bytes(item,report_root)
        async with asyncio.timeout(25):
            async with bot_factory(token=config['bot_token']) as bot:
                me=await bot.get_me(read_timeout=10,connect_timeout=5)
                chat=await bot.get_chat(config['chat_id'],read_timeout=10,connect_timeout=5)
                count=await bot.get_chat_member_count(config['chat_id'],read_timeout=10,connect_timeout=5)
                admins=await bot.get_chat_administrators(config['chat_id'],read_timeout=10,connect_timeout=5)
                if (me.id!=config['bot_id'] or me.username!=config['bot_username'] or chat.id!=config['chat_id']
                        or chat.title!=config['expected_group_title'] or chat.type not in ('group','supergroup')
                        or count!=2 or not any(a.status=='creator' and a.user.id==config['owner_user_id'] for a in admins)):
                    raise PermissionError('Report audience changed')
                sending_at=clock()
                caption=notification_text(item,sending_at,max_length=1024 if documents else 4000)
                if not coordinator.begin_operation(operation,'delivery',dict(outbox_id=item['id'],transport='telegram',chat_id=chat.id)):
                    store.finish(item['id'],'UNKNOWN');return 'UNKNOWN'
                started=True;store.delivery_started(item['id'],sending_at)
                if not documents:
                    messages=[await bot.send_message(chat.id,text=caption,connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)]
                elif len(documents)==1:
                    name,data=documents[0]
                    messages=[await bot.send_document(chat.id,document=data,filename=name,caption=caption,
                        connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)]
                else:
                    from telegram import InputFile,InputMediaDocument
                    media=[InputMediaDocument(InputFile(data,filename=name),caption=caption if i==0 else None)
                           for i,(name,data) in enumerate(documents)]
                    messages=await bot.send_media_group(chat.id,media=media,connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)
                if len(messages)!=max(1,len(documents)) or any(m.chat.id!=chat.id or m.message_id<=0 for m in messages):
                    raise RuntimeError('Native message acknowledgement missing')
                receipt=dict(transport='telegram',chat_id=chat.id,message_ids=[m.message_id for m in messages],
                             server_dates=[m.date.astimezone(timezone.utc).isoformat() for m in messages])
                store.delivery_receipt(item['id'],receipt)
                store.delivery_finished(item['id'],'TELEGRAM_ACCEPTED',ack_at=clock())
                coordinator.observe('TELEGRAM','HEALTHY',freshness='FRESH',reason='Native report message acknowledgement verified',receipt=receipt)
                coordinator.finish_operation(operation,'SENT_ACCEPTED')
                store.finish(item['id'],'TELEGRAM_ACCEPTED')
                return 'TELEGRAM_ACCEPTED'
    except BaseException as exc:
        if started:
            store.delivery_finished(item['id'],'UNKNOWN');coordinator.finish_operation(operation,'UNKNOWN');store.finish(item['id'],'UNKNOWN')
            result='UNKNOWN'
        else:
            result=store.defer_unsent(item['id'])
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        return result
