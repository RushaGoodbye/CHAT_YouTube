#!/usr/bin/env python3
"""Read-only NEWS2 auth source inventory. Never prints or sends credentials."""
import json,os,re,sys
from pathlib import Path
ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2'); OP=ROOT/'operator'
NAMES=['news_rg_poll_moderation_v1.py','rg_poll_topnews_policy_v2.py','news_rg_durable_private_sender_v1.py','news_rg_continuous_callback_v1.py','rg_news_dsm_tick.sh']
TERM=re.compile(r'(?i)(bot.?token|tg.?token|telegram|sendmessage|moderator|chat.?id|config|secret|dotenv|environ|token_file)')
SKIP=('backup','archive','snapshot','recovery','.git','__pycache__','node_modules','venv','site-packages','release','test')
def scripts():
 out=[]
 for name in NAMES:
  p=OP/name
  if not p.is_file() and name=='rg_news_dsm_tick.sh':p=ROOT/name
  try:
   if not p.is_file() or p.is_symlink():continue
   lines=p.read_text('utf8',errors='replace').splitlines()
   hits=[i for i,line in enumerate(lines,1) if TERM.search(line)]
   out.append({'path':str(p),'reference_lines':hits[:50]})
  except OSError:pass
 return out
def candidates():
 out=[];seen=set()
 for base in (ROOT,OP,ROOT/'config',ROOT/'secrets',ROOT/'private',Path('/volume1/docker/RG_ALERTS_DEPLOY')):
  if not base.is_dir() or base.is_symlink():continue
  for parent,dirs,files in os.walk(base):
   depth=len(Path(parent).parts)-len(base.parts)
   dirs[:]=[d for d in dirs if depth<2 and not any(w in d.lower() for w in SKIP)]
   for name in files:
    p=Path(parent)/name
    if p in seen:continue
    seen.add(p)
    if not (name.startswith('.env') or name.endswith(('.env','.json','.ini','.toml','.yaml','.yml','.conf','.cfg','.properties'))):continue
    if any(w in str(p.relative_to(base)).lower() for w in SKIP):continue
    try:
     if p.is_symlink() or p.stat().st_size>200000:continue
     src=p.read_text('utf8',errors='replace')
     keys=sorted(set(x.group(1) for x in re.finditer(r'(?im)^\s*["\x27]?([A-Za-z_][\w]{2,64})["\x27]?\s*[:=]',src)))
     names=[k for k in keys if TERM.search(k)]
     if names:out.append({'path':str(p),'config_key_names':names[:20]})
    except OSError:pass
   if len(out)>30:break
  if len(out)>30:break
 return out
if __name__=='__main__':
 try:
  print(json.dumps({'status':'NEWS2_AUTH_SOURCE_DISCOVERY_READONLY','scripts':scripts(),'active_config_candidates':candidates(),'environment_key_names':[k for k in os.environ if TERM.search(k) and k.startswith(('RG_','TG_','TELEGRAM_','BOT_','NEWS_'))][:25],'secrets_exposed':False,'telegram_calls':0,'publications':0},ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'NEWS2_AUTH_DISCOVERY_SAFE_STOP','error':type(e).__name__,'telegram_calls':0,'publications':0}));sys.exit(2)
