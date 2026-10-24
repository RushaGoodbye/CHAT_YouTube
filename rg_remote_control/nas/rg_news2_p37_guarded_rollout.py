#!/usr/bin/env python3
"""P37 guarded two-file News2 callback rollout. No Telegram API, cron changes, publication.
Requires pinned SHA-1 Git blobs of staging files; reads state and uses two flock locks.
One atomic replacement per file, verified rollback if either replacement fails.
"""
import datetime,fcntl,hashlib,json,os,pathlib,stat,subprocess,sys,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
CR=pathlib.Path('/etc/crontab')
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
ITEMS=[
 ('worker',pathlib.Path('/tmp/rg_news2_p37_worker.py'),O/'rg_news2_p31_guarded_callback_once.py',
  'eceba0756c1de522a24122075c236f4eac5f185e'),
 ('probation',pathlib.Path('/tmp/rg_news2_p37_probation.py'),O/'callback_v29.py',
  '8c2fef89eb62af682afe86f1d7034c87248bc61e')]
def emit(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def sha(b):return hashlib.sha1(('blob %d\0'%len(b)).encode('ascii')+b).hexdigest()
def check():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('OPERATOR_DIRECTORY_UNSAFE')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_POLL_GATE_PRESENT')
 if (B/'PUBLISH_ENABLED').exists() or (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():
  raise RuntimeError('CHANNEL_GATE_OR_OWNER_MODE_UNEXPECTED')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('MODERATION_DELIVERY_GATE_MISSING')
 cr=CR.read_text('utf-8')
 marks=[l for l in cr.splitlines() if 'RG_NEWS2_CALLBACK_PROBATION_V29' in l and not l.lstrip().startswith('#')]
 if len(marks)!=1 or 'callback_v29.py tick' not in marks[0]:
  raise RuntimeError('EXACTLY_ONE_ACTIVE_MINUTE_CRON_REQUIRED')
 state=O/'callback_v29_state.json'
 if not state.is_file() or state.is_symlink():raise RuntimeError('PROBATION_STATE_MISSING')
 s=json.loads(state.read_text('utf-8'))
 if s.get('halt') is not None:raise RuntimeError('PROBATION_ALREADY_HALTED')
 for _,staged,dest,want in ITEMS:
  if not staged.is_file() or staged.is_symlink():raise RuntimeError('STAGED_FILE_MISSING')
  if not dest.is_file() or dest.is_symlink():raise RuntimeError('TARGET_FILE_MISSING')
  data=staged.read_bytes()
  if sha(data)!=want:raise RuntimeError('STAGED_SOURCE_SHA_MISMATCH')
  compile(data,staged.name,'exec')
 return {'attempts':s.get('attempts'),'last_poll':s.get('last_poll_utc')}
def acquire(name):
 fd=os.open(str(O/name),os.O_CREAT|os.O_RDWR,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except (OSError,BlockingIOError):
  os.close(fd);raise RuntimeError('ACTIVE_CALLBACK_PROCESS_RETRY_LATER')
 return fd
def replace(dest,data,oldstat):
 fd,path=tempfile.mkstemp(dir=str(dest.parent),prefix='.news2_p37_')
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.chmod(path,stat.S_IMODE(oldstat.st_mode))
  os.chown(path,oldstat.st_uid,oldstat.st_gid)
  os.replace(path,str(dest))
 finally:
  if os.path.exists(path):os.unlink(path)
def write_once(p,data):
 with os.fdopen(os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
  f.write(data);f.flush();os.fsync(f.fileno())
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('check','apply'):raise RuntimeError('USE_CHECK_OR_APPLY')
 info=check()
 if sys.argv[1]=='check':
  emit(status='NEWS2_P37_PREFLIGHT_PASS',v29_attempts=info['attempts'],
    cron_untouched=True,telegram_calls=0,channel_sends=0);return
 locks=[acquire('callback_v29.lock')]
 try:
  locks.append(acquire('controlled_handoff.lock'))
  info=check()
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
  backup=O/('p37_backup_'+stamp)
  backup.mkdir(mode=0o700)
  replacements=[]
  for name,staged,dest,want in ITEMS:
   orig=dest.read_bytes()
   s=dest.stat()
   write_once(backup/(name+'_before.py'),orig)
   replacements.append((name,staged,dest,want,orig,s))
  installed=[]
  try:
   for name,staged,dest,want,orig,s in replacements:
    replace(dest,staged.read_bytes(),s)
    installed.append((name,dest,orig,s))
   for name,staged,dest,want,orig,s in replacements:
    if sha(dest.read_bytes())!=want:raise RuntimeError('INSTALL_READBACK_SHA_MISMATCH')
   p=subprocess.run(['/usr/bin/python3',str(O/'callback_v29.py'),'status'],
     capture_output=True,text=True,timeout=15)
   try:out=json.loads(p.stdout.strip().splitlines()[-1])
   except Exception:out={}
   if p.returncode!=0 or out.get('status')!='V29_STATUS' or out.get('scheduled') is not True:
    raise RuntimeError('POST_INSTALL_STATUS_FAILED')
  except Exception:
   for name,dest,orig,s in reversed(installed):
    replace(dest,orig,s)
   raise
  write_once(backup/'rollback_readme.txt',
   b'Original News2 worker and probation files. Restore only during a controlled maintenance window.\n')
  emit(status='NEWS2_P37_GUARDED_ROLLOUT_PASS',
   backup_dir=str(backup),installed=['worker','probation'],
   state_attempts=out.get('state',{}).get('attempts'),
   auto_poll_scheduled=out.get('scheduled'),
   real_callback_validation_still_required=True,
   cloudflare_conflict_not_resolved=True,
   cron_changes=0,db_changes=0,telegram_api_calls=0,channel_sends=0)
 finally:
  for fd in reversed(locks):os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='NEWS2_P37_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   cron_changes=0,telegram_api_calls=0,channel_sends=0)
  sys.exit(1)
