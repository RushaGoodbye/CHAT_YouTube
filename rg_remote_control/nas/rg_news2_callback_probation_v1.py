#!/usr/bin/env python3
"""News2 callback probation: automatic 5-minute polling, 24h max, fail-closed.
Uses tested archive-before-ack one-shot module. Does not assert exclusive ownership.
Commands install|tick|status|disable. No channel sends, no owner marker changes.
"""
import datetime,fcntl,json,os,pathlib,stat,subprocess,sys,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2'); O=B/'operator'
CR=pathlib.Path('/etc/crontab'); SRC=O/'rg_news2_controlled_callback_once_v1.py'
STATE=O/'callback_probation_state.json'; LOG=O/'callback_probation.log'
MARK='# RG_NEWS2_CALLBACK_PROBATION_V1'
LINE='*/5\t*\t*\t*\t*\troot\t/usr/bin/python3 /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_probation_v1.py tick >> /volume1/docker/RG_TELEGRAM_NEWS_2/operator/callback_probation.log 2>&1 '+MARK
def emit(**k):print(json.dumps(k,ensure_ascii=False,sort_keys=True),flush=True)
def put(p,t):
 fd,tmp=tempfile.mkstemp(dir=str(p.parent),prefix='.probation_')
 try:
  with os.fdopen(fd,'w') as f:f.write(t);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,0o600);os.replace(tmp,str(p))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def prereq():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink() or not CR.is_file() or CR.is_symlink():raise RuntimeError('OPERATOR_OR_CRON_UNSAFE')
 if not SRC.is_file() or SRC.is_symlink():raise RuntimeError('TESTED_CALLBACK_SCRIPT_MISSING')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_CLOSED')
 if (B/'PUBLISH_ENABLED').exists():raise RuntimeError('CHANNEL_PUBLISH_GATE_MUST_BE_CLOSED')
 if pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled').exists():raise RuntimeError('LEGACY_POLL_GATE_PRESENT')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('OWNER_MODE_CHANGED')
def edit(enable):
 old=CR.read_text('utf-8')
 lines=old.splitlines()
 if any(MARK in s and s!=LINE for s in lines):raise RuntimeError('CRON_MARKER_DRIFT')
 new='\n'.join([s for s in lines if MARK not in s]+([LINE] if enable else []))+'\n'
 if old==new:return False
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 back=O/('crontab_before_callback_probation_'+stamp)
 if back.exists():raise RuntimeError('BACKUP_COLLISION')
 back.write_text(old);os.chmod(str(back),0o600)
 fd,tmp=tempfile.mkstemp(prefix='.news2_callback_',dir='/etc')
 try:
  with os.fdopen(fd,'w') as f:f.write(new);f.flush();os.fsync(f.fileno())
  s=CR.stat();os.chmod(tmp,stat.S_IMODE(s.st_mode));os.chown(tmp,s.st_uid,s.st_gid)
  os.replace(tmp,str(CR))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 if CR.read_text('utf-8')!=new:raise RuntimeError('CRON_READBACK_FAILED')
 return True
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('install','tick','status','disable'):raise RuntimeError('USAGE')
 mode=sys.argv[1];prereq()
 if mode=='status':
  d=json.loads(STATE.read_text('utf-8')) if STATE.is_file() else {}
  emit(status='PROBATION_STATUS',scheduled=MARK in CR.read_text('utf-8'),state=d,channel_sends=0);return
 if mode=='disable':
  changed=edit(False)
  if STATE.is_file():
   d=json.loads(STATE.read_text('utf-8'));d['halt']='operator_disabled';put(STATE,json.dumps(d))
  emit(status='PROBATION_DISABLED',cron_changed=changed);return
 if mode=='install':
  if STATE.exists():raise RuntimeError('ALREADY_INSTALLED_USE_STATUS')
  s=SRC.read_text('utf-8')
  if not all(t in s for t in ('updates_handoff_','process_callback','getUpdates','PUBLISH_ENABLED')):
   raise RuntimeError('UNVERIFIED_CALLBACK_SOURCE')
  d={'started_at':int(time.time()),'expires_at':int(time.time())+86400,'attempts':0,'halt':None,'last':'NOT_RUN'}
  put(STATE,json.dumps(d));edit(True)
  emit(status='PROBATION_SCHEDULED_24H',max_hours=24,cron_every_minutes=5,cron_reload_unverified=True,owner_proven=False,channel_sends=0);return
 fd=os.open(str(O/'callback_probation.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):emit(status='BUSY_SKIP');return
  if not STATE.is_file():raise RuntimeError('PILOT_NOT_INSTALLED')
  d=json.loads(STATE.read_text('utf-8'))
  if d.get('halt') or time.time()>=d['expires_at']:
   if not d.get('halt'):
    d['halt']='expired';put(STATE,json.dumps(d))
   emit(status='HALTED',reason=d['halt'],attempts=d['attempts']);return
  d['attempts']+=1;put(STATE,json.dumps(d))
  try:
   p=subprocess.run(['/usr/bin/python3',str(SRC),'once'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=75)
   output=json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
   if p.returncode!=0 or output.get('status')!='ONE_SHOT_CALLBACK_HANDOFF_COMPLETE':
    d['halt']='poll_failed_or_conflict';d['last']='HALTED';put(STATE,json.dumps(d))
    emit(status='AUTO_HALTED',attempts=d['attempts'],reason='POLL_FAILURE',channel_sends=0);return
   d['last']='PASS';d['last_count']=output.get('update_count',0);put(STATE,json.dumps(d))
   emit(status='CALLBACK_TICK_PASS',attempts=d['attempts'],updates=output.get('update_count',0),
        outcomes=output.get('outcomes',[]),channel_sends=0)
  except Exception:
   d['halt']='unexpected_error';d['last']='HALTED';put(STATE,json.dumps(d))
   emit(status='AUTO_HALTED',reason='UNEXPECTED_ERROR',channel_sends=0)
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__)
  sys.exit(1)
