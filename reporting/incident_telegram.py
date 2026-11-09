"""Telegram report and operational notification delivery with durable no-replay ownership."""
from contextlib import nullcontext
from datetime import timezone
import asyncio
import hashlib
import logging
from pathlib import Path
import re
import time


def validate_config(config):
    if config.get('audience_mode') not in (None,'shared_group'):
        raise PermissionError('Explicit audience mode required')
    if config.get('audience_mode')=='shared_group':
        if config.get('notification_format')!='compact-v1':
            raise PermissionError('Shared group requires privacy-safe compact rendering')
        from .notification_center import recipient
        recipient({'incident_key':'private-target-proof','kind':'SECRETARY_REPLY','payload':{'message_role':'CHAT'}},config)
    extra=config.get('allowed_additional_bots',[])
    if (not isinstance(extra,list) or len(extra)>1
            or any(not isinstance(x,dict) or x.get('username')!='HealthchecksBot'
                   or type(x.get('id')) is not int or x['id']<=0 for x in extra)):
        raise PermissionError('Only the explicitly verified Healthchecks bot may join the audience')
    if (not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{25,}',config.get('bot_token',''))
            or config.get('bot_username')!='deehub_paper_reports_bot'
            or type(config.get('bot_id')) is not int or config['bot_id']<=0
            or type(config.get('chat_id')) is not int or config['chat_id']>=0
            or config.get('expected_group_title') not in ('der','deehub')
            or type(config.get('expected_member_count')) is not int
            or config['expected_member_count']!=2+len(extra) or config.get('target_verified') is not True
            or type(config.get('owner_user_id')) is not int or config['owner_user_id']<=0
            or len({config['owner_user_id'],config['bot_id'],*[x['id'] for x in extra]})!=2+len(extra)):
        raise PermissionError('Verified private der report target required')


async def verify_audience(bot, config):
    """Read-only native proof. Migration requires explicit configuration reconciliation."""
    validate_config(config)
    me=await bot.get_me(read_timeout=10,connect_timeout=5)
    chat=await bot.get_chat(config['chat_id'],read_timeout=10,connect_timeout=5)
    count=await bot.get_chat_member_count(config['chat_id'],read_timeout=10,connect_timeout=5)
    admins=await bot.get_chat_administrators(config['chat_id'],read_timeout=10,connect_timeout=5)
    if (me.id!=config['bot_id'] or me.username!=config['bot_username'] or chat.id!=config['chat_id']
            or chat.title!=config['expected_group_title'] or chat.type not in ('group','supergroup')
            or (config.get('audience_mode')!='shared_group' and count!=config['expected_member_count'])
            or not any(a.status=='creator' and a.user.id==config['owner_user_id'] for a in admins)):
        raise PermissionError('Report audience changed')
    if config.get('allowed_additional_bots'):
        member=await bot.get_chat_member(chat.id,me.id,read_timeout=10,connect_timeout=5)
        if member.status not in ('member','administrator') or member.user.id!=me.id:
            raise PermissionError('Notification bot membership unverified')
        for expected in config['allowed_additional_bots']:
            member=await bot.get_chat_member(chat.id,expected['id'],read_timeout=10,connect_timeout=5)
            if (member.status!='member' or member.user.id!=expected['id']
                    or member.user.username!=expected['username'] or member.user.is_bot is not True):
                raise PermissionError('Additional audience identity or least privilege changed')
    return chat


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


async def verify_destination(bot,config,item):
    validate_config(config)
    from .notification_center import recipient
    target=recipient(item,config)
    if target==config['chat_id']:return await verify_audience(bot,config)
    # Private delivery doesn't depend on group membership, title or friends.
    me=await bot.get_me(read_timeout=10,connect_timeout=5)
    chat=await bot.get_chat(target,read_timeout=10,connect_timeout=5)
    if (me.id!=config['bot_id'] or me.username!=config['bot_username']
            or chat.id!=config['owner_user_id'] or chat.type!='private'):
        raise PermissionError('Exact owner private identity required')
    return chat


async def send_one(store,coordinator,config,*,report_root,claimed_item=None,bot_factory=None,clock=time.time,owned_bot=None,private_proof=None):
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
        from .notification_center import enabled,render,prior_card,stale_schedule
        if stale_schedule(item,clock()):
            store.suppress(item['id']);return 'SUPPRESSED'
        if config.get('notification_format')=='compact-v1' and not enabled(store,item):
            store.suppress(item['id']);return 'SUPPRESSED'
        documents=report_bytes(item,report_root)
        async with asyncio.timeout(25):
            async with (nullcontext(owned_bot) if owned_bot is not None else bot_factory(token=config['bot_token'])) as bot:
                from .notification_center import recipient
                target=recipient(item,config)
                fingerprint=hashlib.sha256(repr(sorted(config.items())).encode()).hexdigest()
                proof_key=(target,fingerprint)
                if target==config.get('owner_private_chat_id') and private_proof is not None and proof_key in private_proof and 0<=clock()-private_proof[proof_key][0]<30:
                    chat=private_proof[proof_key][1]
                else:
                    chat=await verify_destination(bot,config,item)
                    if target==config.get('owner_private_chat_id') and private_proof is not None:
                        private_proof.clear();private_proof[proof_key]=(clock(),chat)
                sending_at=clock()
                caption=notification_text(item,sending_at,max_length=1024 if documents else 4000)
                compact=config.get('notification_format')=='compact-v1'
                if compact:
                    caption=render(item,config,sending_at)['html']
                if config['bot_token'] in caption:
                    raise PermissionError('Credential detected in notification; refuse before wire')
                previous=prior_card(store,item,chat.id) if compact and not documents else None
                formatting={'parse_mode':'HTML'} if compact else {}
                if item['payload'].get('message_role')=='CONTROL' and item['payload'].get('web_app_url'):
                    from telegram import InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
                    url=item['payload']['web_app_url']
                    if not url.startswith('https://') or chat.id!=config.get('owner_private_chat_id'):raise PermissionError('Private HTTPS form required')
                    formatting['reply_markup']=InlineKeyboardMarkup([
                        [InlineKeyboardButton('编辑全部限额',web_app=WebAppInfo(url=url))],
                        [InlineKeyboardButton('门禁与风控的区别',web_app=WebAppInfo(url=url+'#help'))]])
                if not coordinator.begin_operation(operation,'delivery',dict(outbox_id=item['id'],transport='telegram',chat_id=chat.id)):
                    store.finish(item['id'],'UNKNOWN');return 'UNKNOWN'
                started=True;store.delivery_started(item['id'],sending_at)
                if previous:
                    messages=[await bot.edit_message_text(chat_id=chat.id,message_id=previous,text=caption,**formatting,connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)]
                elif not documents:
                    messages=[await bot.send_message(chat.id,text=caption,**formatting,connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)]
                elif len(documents)==1:
                    name,data=documents[0]
                    messages=[await bot.send_document(chat.id,document=data,filename=name,caption=caption,**formatting,
                        connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)]
                else:
                    from telegram import InputFile,InputMediaDocument
                    media=[InputMediaDocument(InputFile(data,filename=name),caption=caption if i==0 else None,**formatting)
                           for i,(name,data) in enumerate(documents)]
                    messages=await bot.send_media_group(chat.id,media=media,connect_timeout=5,read_timeout=20,write_timeout=20,pool_timeout=5)
                if len(messages)!=max(1,len(documents)) or any(m.chat.id!=chat.id or m.message_id<=0 for m in messages):
                    raise RuntimeError('Native message acknowledgement missing')
                receipt=dict(transport='telegram',chat_id=chat.id,message_ids=[m.message_id for m in messages],
                             server_dates=[m.date.astimezone(timezone.utc).isoformat() for m in messages])
                if compact:
                    receipt.update(card_format='compact-v1',delivery_action='EDIT' if previous else 'SEND',
                        entity_types=[[e.type for e in (getattr(m,'entities',None) or getattr(m,'caption_entities',None) or [])] for m in messages])
                store.delivery_receipt(item['id'],receipt)
                store.delivery_finished(item['id'],'TELEGRAM_ACCEPTED',ack_at=clock())
                coordinator.observe('TELEGRAM','HEALTHY',freshness='FRESH',reason='Native report message acknowledgement verified',receipt=receipt)
                coordinator.finish_operation(operation,'SENT_ACCEPTED')
                store.finish(item['id'],'TELEGRAM_ACCEPTED')
                return 'TELEGRAM_ACCEPTED'
    except BaseException as exc:
        # Exception text may contain credential URLs or private payloads.
        logging.getLogger(__name__).warning('notification outcome: id=%s started=%s exception_type=%s',item['id'],started,type(exc).__name__)
        if started:
            store.delivery_finished(item['id'],'UNKNOWN');coordinator.finish_operation(operation,'UNKNOWN');store.finish(item['id'],'UNKNOWN')
            result='UNKNOWN'
        else:
            result=store.defer_unsent(item['id'])
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        return result
