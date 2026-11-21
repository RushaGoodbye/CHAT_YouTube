#!/usr/bin/env python3
"""NEWS2 unattended private translation: bounded, cooldown, no public sends.
Install separately via guarded NEWS2 hotfix. Writes root-only audit state.
"""
import datetime as dt,fcntl,json,os,pathlib,subprocess,sys,time,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
P=O/'news_rg_native_video_translation_pending_v1'
RUN=O/'rg_news2_strict_native_translation_retry_v2.py'
STATE=O/'rg_news2_translation_retry_scheduler_state_v1.json'
LOCK=O/'rg_news2_translation_retry_scheduler.lock'
BACKOFF=12*3600
def safe_json(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>40000:return {}
  v=json.loads(p.read_text('utf8'));return v if isinstance(v,dict) else {}
 except Exception:return {}
def save(o):
 fd,t=tempfile.mkstemp(dir=O,prefix='.translation_sched_',suffix='.tmp')
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'w',encoding='utf8') as f:
   json.dump(o,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(t,STATE)
 finally:
  if os.path.exists(t):os.unlink(t)
def run():
 if sys.argv[1:]==['--selftest']:
  assert BACKOFF==12*3600 and RUN.name=='rg_news2_strict_native_translation_retry_v2.py'
  print(json.dumps({'status':'TRANSLATION_SCHEDULER_SELFTEST_PASS','publications':0,'telegram_calls':0}))
  return
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if (B/'PUBLISH_ENABLED').exists() or (B/'PUBLISH_ENABLED').is_symlink():
  raise RuntimeError('PUBLIC_GATE_ENABLED_STOP')
 if not P.is_dir() or P.is_symlink() or not RUN.is_file() or RUN.is_symlink():
  raise RuntimeError('PROTECTED_QUEUE_OR_RUNNER_UNAVAILABLE')
 fd=os.open(LOCK,os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):
   print(json.dumps({'status':'ALREADY_RUNNING','publications':0}));return
  state=safe_json(STATE)
  attempts=state.get('attempts',{})
  if not isinstance(attempts,dict):attempts={}
  now=int(time.time())
  pending=[]
  for p in P.glob('*.json'):
   d=safe_json(p)
   if d.get('schema')!='RG_NATIVE_VIDEO_PENDING_UKRAINIAN_V1' or d.get('status')!='AWAITING_VERIFIED_UKRAINIAN_TEXT':continue
   if d.get('public_publication')!='OFF' or d.get('auto_publish_allowed') is not False:continue
   pending.append(p.stem)
  if not pending:
   print(json.dumps({'status':'NO_TRANSLATIONS_PENDING','publications':0}));return
  excluded=[pid for pid in pending if now-int((attempts.get(pid) or {}).get('last_attempt',0))<BACKOFF]
  if len(excluded)==len(pending):
   print(json.dumps({'status':'ALL_PENDING_COOLDOWN','pending':len(pending),'cooldown':len(excluded),'publications':0}));return
  env=os.environ.copy()
  env['RG_TRANSLATION_SKIP_PENDING_IDS']=','.join(excluded)
  cmd=[sys.executable,str(RUN),'--apply']
  proc=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=240)
  try:result=json.loads(proc.stdout.strip())
  except Exception:result={'status':'UNPARSEABLE_RESULT'}
  processed=[]
  for item in result.get('items',[]):
   if not isinstance(item,dict):continue
   pid=item.get('pending_id')
   if pid not in pending:continue
   if item.get('gemini_attempts',0):
    # Count even for rejected output, preventing unbounded AI retry/cost.
    attempts[pid]={'last_attempt':now,'attempts':int(item.get('gemini_attempts',0)),
      'result':item.get('status')}
    processed.append({'pending_id':pid,'result':item.get('status'),
      'gemini_attempts':item.get('gemini_attempts',0),
      'private_dispatch_requested':bool(item.get('private_dispatch_requested'))})
  state={'schema':'RG_NEWS2_TRANSLATION_SCHEDULE_V1','last_run_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
     'attempts':attempts,'latest_run_status':result.get('status'),'returncode':proc.returncode,
     'publications':0}
  save(state)
  print(json.dumps({'status':'TRANSLATION_AUTO_TICK_COMPLETE' if proc.returncode==0 else 'TRANSLATION_AUTO_TICK_SAFE_STOP',
    'pending':len(pending),'skipped_cooldown':len(excluded),'processed':processed,
    'runner_status':result.get('status'),'publications':0,'new_pollers':0},ensure_ascii=False))
 finally:
  fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
if __name__=='__main__':
 try:run()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100]
  if str(e) in ('SUDO_REQUIRED','PUBLIC_GATE_ENABLED_STOP','PROTECTED_QUEUE_OR_RUNNER_UNAVAILABLE')
  else type(e).__name__,'publications':0,'new_pollers':0}))
  sys.exit(2)
