#!/usr/bin/env python3
"""Fail-closed upgrade of legacy single-card private sender; no sends during install."""
import os,pathlib,subprocess,sys,hashlib,tempfile,json,stat
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
D=O/'news_rg_durable_private_sender_v1.py'
S=pathlib.Path('/tmp/news_rg_durable_private_sender_v1.py')
def fail(s):raise RuntimeError(s)
def install():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if O.is_symlink() or not O.is_dir():fail('OPERATOR_UNSAFE')
 for p in (D,S,O/'news_rg_multipart.py',O/'news_rg_wrong_photo_supersession_v1.py'):
  if p.is_symlink() or not p.is_file():fail('FILE_MISSING_OR_UNSAFE_'+p.name)
 old=D.read_bytes();new=S.read_bytes()
 if len(old)>100000 or len(new)>100000:fail('SCRIPT_TOO_LARGE')
 if old==new:return {'status':'SENDER_ALREADY_CURRENT','telegram_sends':0,'publications':0}
 before=old.decode('utf8');after=new.decode('utf8')
 if 'WAITING_FOR_EDITORIAL_DECISION' not in before:fail('UNEXPECTED_LIVE_VERSION')
 if not all(x in after for x in ('MAX_OUTSTANDING=20','MAX_OUTSTANDING_PRIVATE_CARDS_20','SENDING_UNCERTAIN','PRIVATE_SENT_CONFIRMED','news_rg_wrong_photo_supersession_v1')):fail('UNEXPECTED_NEW_VERSION')
 if 'WAITING_FOR_EDITORIAL_DECISION' in after or 'getUpdates(' in after:fail('UNSAFE_NEW_VERSION')
 env=dict(os.environ);env['PYTHONPATH']=str(O)+os.pathsep+env.get('PYTHONPATH','')
 t=subprocess.run(['/usr/bin/python3',str(S),'selftest'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
 if t.returncode or b'SELFTEST_PASS' not in t.stdout:fail('NEW_SENDER_SELFTEST_FAILED')
 backup=O/('news_rg_sender_before_20_'+hashlib.sha256(old).hexdigest()[:16]+'.py')
 if backup.exists() or backup.is_symlink():fail('BACKUP_ALREADY_EXISTS')
 fd,tmp=tempfile.mkstemp(prefix='.rg_sender_bak_',dir=str(O))
 try:
  with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),0o600);f.write(old);f.flush();os.fsync(f.fileno())
  os.link(tmp,backup)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 if D.read_bytes()!=old:fail('LIVE_CHANGED_DURING_UPGRADE')
 st=D.stat();fd,tmp=tempfile.mkstemp(prefix='.rg_sender_new_',dir=str(O))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),stat.S_IMODE(st.st_mode));os.fchown(f.fileno(),st.st_uid,st.st_gid)
   f.write(new);f.flush();os.fsync(f.fileno())
  os.replace(tmp,D)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 t=subprocess.run(['/usr/bin/python3',str(D),'selftest'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
 if t.returncode or b'SELFTEST_PASS' not in t.stdout:
  # Restore pre-verified exact prior bytes before returning failure.
  fd,tmp=tempfile.mkstemp(prefix='.rg_sender_restore_',dir=str(O))
  try:
   with os.fdopen(fd,'wb') as f:
    os.fchmod(f.fileno(),stat.S_IMODE(st.st_mode));os.fchown(f.fileno(),st.st_uid,st.st_gid)
    f.write(old);f.flush();os.fsync(f.fileno())
   os.replace(tmp,D)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  fail('POSTINSTALL_SELFTEST_FAILED_ROLLED_BACK')
 return {'status':'SENDER_20_INSTALLED','backup':str(backup),'telegram_sends':0,'publications':0,'dsm_tasks_added':0,'pollers_added':0}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:print('NEWS_RG_SENDER_20_UPGRADE_SELFTEST_PASS')
  elif sys.argv[1:]==['install']:print(json.dumps(install()))
  else:fail('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,'telegram_sends':0,'publications':0}));sys.exit(2)
