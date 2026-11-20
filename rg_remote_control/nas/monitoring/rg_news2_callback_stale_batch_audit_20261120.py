#!/usr/bin/env python3
"""NEWS2 callback stale: one-shot redacted read-only diagnostics.
No state modification, no Telegram calls, no process restarts, no new poller.
"""
import os, pathlib, json, hashlib, time, re, subprocess, sys, datetime
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=R/'operator'
MATCH=re.compile(r'(?i)(callback|telegram.*stale|moderation.*stale|poll.*moderation|poll.*callback|continuous.callback|singleton)')
SENSITIVE=re.compile(r'(?i)(token|secret|password|authorization|api_key|https?://api.telegram.org/bot)')
PATHS=[
 O/'news_rg_continuous_callback_v1.py',
 O/'rg_news2_p31_guarded_callback_once.py',
 O/'news_rg_poll_moderation_v1.py',
 O/'news_rg_stability_releases_v1/guard_cron.log',
 O/'news_rg_continuous_callback_v1.log',
 O/'news_rg_stability_releases_v1/guard_last_tick.json',
 O/'news_rg_stability_releases_v1/pinned_release_v1.json',
 R/'rg_news_dsm_tick.sh'
]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def info(path):
 if not path.is_file() or path.is_symlink():return None
 st=path.stat()
 return {'name':path.name,'modified_utc':datetime.datetime.fromtimestamp(st.st_mtime,datetime.timezone.utc).isoformat(),
  'size':st.st_size, 'sha256':sha(path) if path.name in ('news_rg_poll_moderation_v1.py','news_rg_continuous_callback_v1.py','rg_news2_p31_guarded_callback_once.py') else None}
def process_inventory():
 # Never read environment or command-line arguments containing secrets.
 output=[]
 proc=pathlib.Path('/proc')
 for p in proc.iterdir():
  if not p.name.isdecimal():continue
  try:
   raw=(p/'cmdline').read_bytes()
   args=[a.decode('utf8',errors='replace') for a in raw.split(b'\0') if a]
   if any(MATCH.search(os.path.basename(a)) for a in args):
    paths=[os.path.basename(a) for a in args if '/' in a or a.endswith('.py')]
    output.append({'pid':int(p.name),'program_basenames':paths[:8]})
  except (OSError,PermissionError,ProcessLookupError):pass
 return output[:30]
def logs():
 paths=[]
 roots=(O,R)
 for root in roots:
  try:items=list(root.iterdir())
  except OSError:continue
  for p in items:
   if p in PATHS or any(k in p.name.lower() for k in ('callback','watchdog','health','poll','moderation')):
    if p.is_file() and p.suffix.lower() in ('.log','.json','.txt','.state') and not p.is_symlink():
     paths.append(p)
 paths +=[x for x in PATHS if x.suffix=='.log']
 results=[];seen=set()
 for p in paths:
  if p in seen:continue
  seen.add(p)
  try:
   if p.stat().st_size>4000000:continue
   lines=p.read_text('utf8',errors='replace').splitlines()
   hits=[]
   for line in lines[-150:]:
    if MATCH.search(line) or re.search(r'(?i)(stale|error|failed|exception|alert)',line):
     if SENSITIVE.search(line):continue
     # Only output small, redacted text for status diagnostics.
     line=re.sub(r'(?i)(chat_id|user_id|moderator_id)\W{0,8}\d+',r'\1=[REDACTED]',line)
     line=re.sub(r'[0-9]{8,12}:[A-Za-z0-9_-]{20,}','[REDACTED]',line)
     if len(line)<280:hits.append(line.strip())
   if hits:results.append({'file':p.name,'mtime':int(p.stat().st_mtime),'matched_tail':hits[-8:]})
  except (OSError,UnicodeError):pass
 return results[:20]
def schedules():
 shell=R/'rg_news_dsm_tick.sh'
 if not shell.is_file():return []
 text=shell.read_text('utf8',errors='replace').splitlines()
 return [{'line':i,'executed_module':os.path.basename(s.strip().split()[1]) if len(s.strip().split())>1 else 'UNKNOWN'}
  for i,s in enumerate(text,1) if 'callback' in s.lower() and not SENSITIVE.search(s)][:12]
def main():
 files=[info(p) for p in PATHS]
 poll=O/'news_rg_poll_moderation_v1.py'
 expected='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
 guard= poll.is_file() and sha(poll)==expected
 result={'status':'RG_NEWS2_CALLBACK_STALE_READONLY_AUDIT','poll_v6_pinned_live':guard,
  'current_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'files':[f for f in files if f], 'processes':process_inventory(),
  'matched_logs':logs(),'callback_scheduler_references':schedules(),
  'telegram_calls':0,'publications':0,'new_pollers':0,'restarts':0,
  'assessment':'REQUIRES_OPERATOR_REVIEW_NO_AUTO_RESTART'}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'RG_NEWS2_CALLBACK_DIAGNOSTIC_SAFE_STOP','error':type(e).__name__,
   'telegram_calls':0,'publications':0},ensure_ascii=False));sys.exit(2)
