#!/usr/bin/env python3
"""NEWS RG durable PRIVATE automation cutover using the existing Synology DSM tick.
No extra cron, second getUpdates, public posting or automatic publication approval.
Fail closed before live edit; restore original task script on errors.
"""
import os,sys,re,json,pathlib,subprocess,hashlib,stat,tempfile,shutil
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
T=B/'rg_news_dsm_tick.sh'
TAG='# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1'
ISOLATED='# NEWS_RG_ISOLATED_SCHEDULE_V2'
INPUTS={
 '/tmp/news_rg_private_multipart_preflight_v1.py':O/'news_rg_multipart.py',
 '/tmp/news_rg_durable_private_sender_v1.py':O/'news_rg_durable_private_sender_v1.py',
 '/tmp/news_rg_durable_private_dispatch_v1.py':O/'news_rg_durable_private_dispatch_v1.py'}
SCHED=O/'news_rg_private_dispatch_schedule_v1.py'
SCHEDULE_CODE="""#!/usr/bin/env python3
import os,sys,time,fcntl,pathlib,subprocess
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
DISPATCH=O/'news_rg_durable_private_dispatch_v1.py'
def main():
 if os.geteuid()!=0:return
 fd=os.open(str(O/'news_rg_dispatch_schedule.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):return
  last=O/'news_rg_private_dispatch_last_launch'
  now=time.time()
  if last.exists():
   try:
    if now-float(last.read_text())<1800:return
   except (OSError,ValueError):return
  # Only attempt private delivery if a REAL editorial decision was recorded.
  gate=subprocess.run(['/usr/bin/python3',str(DISPATCH),'status'],
    capture_output=True,text=True,timeout=8)
  if gate.returncode or '"status": "PRIVATE_DISPATCH_ARMED"' not in gate.stdout:return
  logfd=os.open(str(O/'news_rg_private_dispatch_autorun.log'),
    os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
  try:
   subprocess.Popen(['/usr/bin/python3',str(DISPATCH),'run-once'],
    stdin=subprocess.DEVNULL,stdout=logfd,stderr=logfd,start_new_session=True)
   last.write_text(str(now));os.chmod(last,0o600)
  finally:os.close(logfd)
 finally:os.close(fd)
if __name__=='__main__' and sys.argv[1:]==['tick']:
 main()
"""
TRAILER="""# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1
# One existing DSM task; private-only review. No getUpdates or public publication.
/usr/bin/python3 '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_private_dispatch_schedule_v1.py' tick >/dev/null 2>&1 || :
exit 0
"""
def fail(why):raise RuntimeError(why)
def report(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True))
def atomic(p,buf,mode):
 fd,tmp=tempfile.mkstemp(dir=str(p.parent),prefix='.news_rg_cutover_')
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   f.write(buf);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def preflight():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 for p in (B,O):
  if not p.is_dir() or p.is_symlink():fail('DIRECTORY_UNSAFE')
 if not T.is_file() or T.is_symlink():fail('DSM_TICK_MISSING')
 src=T.read_text(encoding='utf-8')
 if src.count(ISOLATED)!=1:fail('ISOLATED_SCHEDULE_NOT_UNIQUE')
 if '# RG_NEWS2_PRIVATE_FINAL_V1' not in src or 'rg_news2_private_final_guard_v1.py' not in src:
  fail('GUARDED_TICK_CONTRACT_CHANGED')
 for path in [O/'rg_news2_p31_guarded_callback_once.py',B/'rg_moderation.py',O/'news_rg_editorial_callbacks_v1.py']:
  if not path.is_file() or path.is_symlink():fail('EDITORIAL_ROUTE_MISSING')
 if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in (O/'rg_news2_p31_guarded_callback_once.py').read_text():
  fail('EDITORIAL_WORKER_PATCH_MISSING')
 if '# NEWS_RG_EDITORIAL_HOOK_V1' not in (B/'rg_moderation.py').read_text():
  fail('EDITORIAL_PROCESS_CALLBACK_MISSING')
 if TAG in src:
  return src,None,True
 for source,dest in INPUTS.items():
  p=pathlib.Path(source)
  if not p.is_file() or p.is_symlink():fail('STAGE_MISSING_'+p.name)
  if dest.is_symlink():fail('DEST_SYMLINK_'+dest.name)
  text=p.read_text(encoding='utf-8')
  if dest.name=='news_rg_multipart.py' and 'MULTIPART_SELFTEST_PASS' not in text:fail('UNKNOWN_TRANSPORT')
  if dest.name=='news_rg_durable_private_sender_v1.py' and 'PRIVATE_SENT_CONFIRMED' not in text:fail('UNKNOWN_SENDER')
  if dest.name=='news_rg_durable_private_dispatch_v1.py' and 'WAITING_FOR_REAL_EDITORIAL_CALLBACK' not in text:fail('UNKNOWN_DISPATCH')
  if dest.exists() and dest.read_text(encoding='utf-8')!=text:fail('DESTINATION_DIFFERENT_'+dest.name)
  check=subprocess.run(['/usr/bin/python3','-m','py_compile',str(p)],
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)
  if check.returncode:fail('PYTHON_SYNTAX_FAILED_'+p.name)
 if SCHED.exists() and SCHED.is_symlink():fail('SCHEDULER_SYMLINK')
 if TAG in src:fail('PATCH_ALREADY_PRESENT')
 # The prior V2 launcher was appended AFTER an unconditional 'exit $?'.
 # Replace that exit with a guarded return-code check, enabling existing staging.
 head,sep,tail=src.partition(ISOLATED)
 if not sep:fail('STAGING_ANCHOR_MISSING')
 match=re.search(r'(?m)^exit \$\?[ \t]*$',head)
 if not match:fail('UNREACHABLE_EXIT_ANCHOR_NOT_FOUND')
 if head[match.end():].strip():fail('GUARDED_EXIT_NOT_LAST_IN_PREFIX')
 if 'exit ' in tail or 'exit\t' in tail:fail('UNEXPECTED_EXIT_IN_STAGING_TRAILER')
 updated_head=head[:match.start()]+'rg_news_guard_rc=$?\nif [ "$rg_news_guard_rc" -ne 0 ]; then exit "$rg_news_guard_rc"; fi\n'
 patched=updated_head+ISOLATED+tail.rstrip()+'\n'+TRAILER
 result=subprocess.run(['sh','-n'],input=patched,text=True,capture_output=True,timeout=10)
 if result.returncode:fail('DSM_SHELL_SYNTAX_INVALID')
 return src,patched,False
def install():
 previous,updated,already=preflight()
 if already:return {'status':'AUTOMATION_ALREADY_INSTALLED','publications':0}
 bk=O/('rg_news_dsm_tick.before_private_automation_'+hashlib.sha256(previous.encode()).hexdigest()[:16]+'.sh')
 if bk.is_symlink():fail('BACKUP_SYMLINK')
 if not bk.exists():atomic(bk,previous.encode('utf-8'),0o600)
 installed=[]
 old_sched=SCHED.read_bytes() if SCHED.is_file() and not SCHED.is_symlink() else None
 try:
  for source,dest in INPUTS.items():
   if not dest.exists():
    atomic(dest,pathlib.Path(source).read_bytes(),0o600)
    installed.append(dest)
  atomic(SCHED,SCHEDULE_CODE.encode('utf-8'),0o700)
  for name in ('news_rg_multipart.py','news_rg_durable_private_sender_v1.py','news_rg_durable_private_dispatch_v1.py'):
   p=O/name
   test=subprocess.run(['/usr/bin/python3',str(p),'selftest'],
      capture_output=True,text=True,timeout=12)
   if test.returncode or 'SELFTEST_PASS' not in test.stdout:fail('DURABLE_SELFTEST_FAILED_'+name)
  cmd=subprocess.run(['/usr/bin/python3','-m','py_compile',str(SCHED)],capture_output=True,text=True,timeout=12)
  if cmd.returncode:fail('SCHEDULER_SYNTAX_FAILED')
  mode=stat.S_IMODE(T.stat().st_mode)
  atomic(T,updated.encode('utf-8'),mode)
  live=T.read_text('utf-8')
  if TAG not in live or 'rg_news_guard_rc=$?' not in live:fail('POSTINSTALL_TICK_VERIFY_FAILED')
 except Exception:
  atomic(T,previous.encode('utf-8'),stat.S_IMODE(T.stat().st_mode))
  if old_sched is None:
   if SCHED.exists():SCHED.unlink()
  else:atomic(SCHED,old_sched,0o700)
  for path in installed:
   if path.exists():path.unlink()
  raise
 # Private delivery is armed ONLY after the anchor's REAL editorial callback is proven.
 check=subprocess.run(['/usr/bin/python3',str(O/'news_rg_durable_private_dispatch_v1.py'),'status'],
   capture_output=True,text=True,timeout=12)
 return {'status':'NEWS_RG_PRIVATE_AUTOMATION_INSTALLED','dsm_tasks_added':0,
  'existing_dsm_tick_enabled':True,'prior_staging_launcher_reachable':True,
  'private_dispatch_gate':check.stdout.strip()[:300],
  'backup':str(bk),'publications':0,'telegram_sends':0,'new_pollers':0}
def main():
 mode=sys.argv[1:]
 if mode==['selftest']:
  assert '# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1' in TRAILER
  assert 'getUpdates' not in SCHEDULE_CODE
  print('NEWS_RG_PRIVATE_AUTOMATION_INSTALLER_SELFTEST_PASS')
 elif mode==['preflight']:
  old,new,already=preflight()
  report(status='ALREADY_INSTALLED' if already else 'CUTOVER_PREFLIGHT_PASS',
      previous_tick_sha256=hashlib.sha256(old.encode()).hexdigest()[:16],
      patches=['reach_existing_staging','private_dispatch_schedule'] if not already else [],
      telegram_sends=0,publications=0)
 elif mode==['install']:report(**install())
 else:fail('BAD_MODE')
if __name__=='__main__':
 try:main()
 except Exception as e:
  report(status='SAFE_STOP',reason=str(e)[:110],publications=0,telegram_sends=0)
  sys.exit(2)
