"""On-demand Telegram user search. Private session is host-only, not a model tool."""
import asyncio
from datetime import timezone
import json
import logging
import re
from .errors import redact


def request_values(request):
    if not isinstance(request,dict) or set(request)-{'query','limit','before_id'}:raise ValueError('Only bounded query, limit and before_id supported')
    q=request.get('query','');limit=request.get('limit',10);before=request.get('before_id',0)
    if not isinstance(q,str) or not 1<=len(q.strip())<=200 or type(limit) is not int or not 1<=limit<=20 or type(before) is not int or not 0<=before<=2**31-1:
        raise ValueError('Bounded search query required')
    return q.strip(),limit,before


async def search(path,request,expected,*,client_factory=None,peer_factory=None):
    q,limit,before=request_values(request)
    base={'source':'telegram_live','rows':[],'history_mirrored':False,'untrusted_evidence':True}
    if not path.exists():return {**base,'state':'NEEDS_OWNER_USER_SESSION','reason':'No approved user session; Bot API cannot search group history'}
    if path.is_symlink() or path.stat().st_mode&0o077 or path.stat().st_size>16000:raise PermissionError('Private mode0600 bounded search configuration required')
    cfg=json.loads(path.read_text())
    if (cfg.get('approved') is not True or cfg.get('owner_user_id')!=expected['owner_user_id'] or cfg.get('chat_id')!=expected['chat_id']
        or type(cfg.get('api_id')) is not int or cfg['api_id']<=0 or not re.fullmatch('[a-fA-F0-9]{32}',cfg.get('api_hash',''))
        or not isinstance(cfg.get('session'),str) or not 1<=len(cfg['session'])<=10000
        or type(cfg.get('channel_access_hash')) is not int or not str(expected['chat_id']).startswith('-100')):
        raise PermissionError('Explicit owner and exact der-group user search session required')
    senders=expected.get('bot_ids',[])
    if not senders or len(senders)>10 or any(type(x) is not int or x<=0 for x in senders):raise PermissionError('Verified bot sender allowlist required')
    if client_factory is None:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            from telethon.tl.types import InputPeerChannel
        except ImportError:return {**base,'state':'DEPENDENCY_NOT_INSTALLED','reason':'Reviewed Telethon dependency and owner login required'}
        client_factory=lambda c:TelegramClient(StringSession(c['session']),c['api_id'],c['api_hash'],
            receive_updates=False,auto_reconnect=False,connection_retries=0,request_retries=0,flood_sleep_threshold=0)
        peer_factory=InputPeerChannel
    logging.getLogger('telethon').setLevel(logging.CRITICAL)
    client=client_factory(cfg);rows=[];scanned=0;offset=before;result=None
    try:
        async with asyncio.timeout(25):
            await client.connect()
            if not await client.is_user_authorized():return {**base,'state':'NEEDS_OWNER_LOGIN','reason':'User session not authorized; no login or code request attempted'}
            me=await client.get_me()
            if me.id!=expected['owner_user_id'] or me.bot:raise PermissionError('Exact owner user session required')
            channel=int(str(expected['chat_id'])[4:]);peer=peer_factory(channel,cfg['channel_access_hash'])
            async for msg in client.iter_messages(peer,search=q,limit=100,offset_id=before):
                scanned+=1;offset=msg.id
                if msg.sender_id not in senders:continue
                rows.append({'message_id':msg.id,'sender_id':msg.sender_id,
                    'date':msg.date.astimezone(timezone.utc).isoformat(),
                    'text':redact((msg.message or '[non-text message; no OCR/transcription performed]')[:2000]),
                    'url':'https://t.me/c/'+str(channel)+'/'+str(msg.id)})
                if len(rows)>=limit:break
            result={**base,'state':'SEARCHED','rows':rows,'next_before_id':offset or None,
                    'scan_limit':100,'scanned':scanned,'possibly_more':scanned>=100 or len(rows)>=limit,
                    'scope':'Exact der group and verified bot sender IDs; no global search, sends, read acknowledgement or media download'}
    except PermissionError:raise
    except Exception as exc:
        result={**base,'state':'SEARCH_UNAVAILABLE','error_type':type(exc).__name__,'reason':'No automatic login, retry or flood wait; inspect host privately'}
    finally:
        await asyncio.wait_for(client.disconnect(),timeout=5)
    return result


def message(data):
    lines=['Telegram群内搜索｜'+data['state']]
    if data.get('reason'):lines.append(data['reason'])
    for row in data.get('rows',[]):lines.extend([row['date']+' · '+row['url'],row['text'][:400]])
    if data['state']=='SEARCHED' and not data.get('rows'):lines.append('本次扫描未返回匹配机器人消息；不是完整历史不存在的证明。')
    if data.get('possibly_more'):lines.append('可继续 before_id='+str(data.get('next_before_id')))
    return str(redact('\n'.join(lines)))[:2900]
