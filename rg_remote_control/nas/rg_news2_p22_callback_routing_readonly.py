#!/usr/bin/env python3
"""RG Telegram News2 P22. READ ONLY: identify origin of old moderation button
and enumerate local consumers of Telegram getUpdates. No polling or sending.
"""
import ast,collections,datetime,json,os,pathlib,re,sqlite3,subprocess,sys,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
def emit(d):print(json.dumps(d,ensure_ascii=False,indent=2),flush=True)
def load(p):
 try:return json.loads(p.read_text('utf-8'))
 except Exception:return {}
def callbacks():
 results=[]
 for f in sorted(O.glob('updates_handoff_*.json')):
  d=load(f)
  for upd in d.get('updates',[]):
   cb=upd.get('callback_query') if isinstance(upd,dict) else None
   if not isinstance(cb,dict):continue
   mes=cb.get('message') or {}
   chat=mes.get('chat') or {}
   bot=mes.get('from') or {}
   person=cb.get('from') or {}
   data=cb.get('data') or ''
   buttons=[]
   rm=mes.get('reply_markup') or {}
   for row in rm.get('inline_keyboard',[]):
    if not isinstance(row,list):continue
    for button in row:
     if not isinstance(button,dict):continue
     bd=button.get('callback_data') or ''
     buttons.append({'caption':str(button.get('text',''))[:50],
        'data_prefix':':'.join(str(bd).split(':')[:2])[:55],
        'has_callback_data':bool(bd)})
   results.append({'archive':f.name,'update_id':upd.get('update_id'),
    'message_id':mes.get('message_id'),
    'message_bot_username':bot.get('username'),
    'message_bot_is_bot':bot.get('is_bot'),
    'click_actor_is_bot':person.get('is_bot'),
    'callback_data_prefix':':'.join(str(data).split(':')[:2])[:55],
    'keyboard_buttons':buttons[:12],
    'chat_type':chat.get('type'),
    'message_from_present':bool(bot)})
 return results[-10:]
def checked_bin(a,t=12):
 try:
  x=subprocess.run(a,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=t)
  return (x.returncode,x.stdout)
 except Exception:return 99,''
def paths():
 # Search only shallow RG-owned integration source trees; never follow symlinks.
 root=pathlib.Path('/volume1/docker')
 sources=[]
 checked=0
 ignore={'node_modules','.git','venv','.venv','site-packages','__pycache__','backups','archive','data','cache','logs'}
 for top in sorted(root.iterdir()):
  if not top.is_dir() or top.is_symlink() or not top.name.startswith(('RG_','rg-','rg_')):continue
  for cur,dirs,files in os.walk(str(top),followlinks=False):
   rel=pathlib.Path(cur).relative_to(top)
   level=len(rel.parts) if str(rel)!='.' else 0
   dirs[:]=[d for d in dirs if d not in ignore and not pathlib.Path(cur,d).is_symlink()] if level<3 else []
   for filename in files:
    checked+=1
    if checked>6000 or len(sources)>=80:return sources
    path=pathlib.Path(cur,filename)
    if path.suffix.lower() not in ('.py','.js','.mjs','.cjs','.sh','.ts'):continue
    try:
     if path.is_symlink() or path.stat().st_size>350000:continue
     data=path.read_text('utf-8',errors='replace')
    except Exception:continue
    if re.search(r'getUpdates|start_polling|run_polling|infinity_polling|polling\s*=',data,re.I):
     relpath=path.relative_to(root)
     sources.append({'path':str(relpath)[:180],
       'getUpdates':bool(re.search(r'getUpdates',data,re.I)),
       'polling_framework':bool(re.search(r'start_polling|run_polling|infinity_polling|polling\s*=',data,re.I))})
 return sources
def main():
 if os.geteuid()!=0:
  emit({'status':'P22_BLOCKED','reason':'SUDO_REQUIRED'});sys.exit(1)
 if not B.is_dir() or not O.is_dir():
  emit({'status':'P22_BLOCKED','reason':'NEWS2_DIR_MISSING'});sys.exit(1)
 sys.path.insert(0,str(B))
 import rg_moderation as m
 cfg=m.config()
 current={'configured_moderation_chat_is_authorized':cfg['moderation_chat_id'] in cfg['moderators']}
 try:
  # getMe does not poll updates, acknowledge callbacks, or send anything.
  me=m.api('getMe',{})
  current.update({'current_bot_username':me.get('username'),'current_bot_id':me.get('id')})
 except Exception as ex:current['getMe_error_type']=type(ex).__name__
 seen=callbacks()
 for item in seen:
  item['origin_matches_current_bot']=item['message_bot_username']==current.get('current_bot_username') if item['message_bot_username'] else None
 report={'status':'NEWS2_P22_CALLBACK_ROUTING_READ_ONLY','time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'current_bot':current,'archived_callbacks':seen,
  'possible_local_pollers_by_source':paths(),
  'cron_related_lines':[],
  'channel_sends':0,'getUpdates_calls':0,'file_changes':0}
 cr=pathlib.Path('/etc/crontab')
 if cr.is_file():
  for line in cr.read_text('utf-8',errors='replace').splitlines():
   if 'TELEGRAM' in line.upper() or 'NEWS2' in line.upper():
    report['cron_related_lines'].append({'news2_related':'NEWS2' in line.upper(),
      'callback_polling_marker':'CALLBACK' in line.upper(),
      'has_getupdates_literal':'getUpdates' in line,'schedule':line.split(maxsplit=5)[:5]})
 emit(report)
if __name__=='__main__':main()
