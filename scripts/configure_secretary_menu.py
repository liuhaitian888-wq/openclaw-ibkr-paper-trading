"""Preview by default; apply only to the verified owner's private command scope."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reporting.secretary_controls import menu_commands


async def configure(path,apply=False):
    if path.stat().st_mode&0o077:raise PermissionError('Private Telegram configuration required')
    config=json.loads(path.read_text())
    from reporting.incident_telegram import verify_destination
    from telegram import Bot,BotCommand,BotCommandScopeChat
    commands=menu_commands()
    if not apply:return {'scope':'verified owner private chat','commands':commands,'applied':False}
    async with Bot(token=config['bot_token']) as bot:
        await verify_destination(bot,config,dict(incident_key='menu-proof',kind='SECRETARY_REPLY',payload={}))
        scope=BotCommandScopeChat(config['owner_private_chat_id'])
        expected=[BotCommand(*x) for x in commands]
        if not await bot.set_my_commands(expected,scope=scope):raise RuntimeError('Menu ACK missing')
        actual=await bot.get_my_commands(scope=scope)
        if [(x.command,x.description) for x in actual]!=commands:raise RuntimeError('Menu readback mismatch')
        return {'scope':'verified owner private chat','commands':commands,'applied':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--preview',action='store_true');group.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(asyncio.run(configure(Path.home()/'.config/openclaw/telegram.json',args.apply)),ensure_ascii=False))
