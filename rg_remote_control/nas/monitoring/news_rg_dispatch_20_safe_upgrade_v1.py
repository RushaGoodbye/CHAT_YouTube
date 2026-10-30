#!/usr/bin/env python3
"""Guarded replacement of legacy one-card gate with verified 20-card sender.
No Telegram calls, no publishing, no poller, no scheduler changes.
"""
import hashlib,json,os,pathlib,subprocess,sys,tempfile,stat
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
DST=O/'news_rg_durable_private_dispatch_v1.py'
SRC=pathlib.Path('/tmp/news_rg_durable_private_dispatch_v1.py')
NEEDED=('ONE_OUTSTANDING_EDITORIAL_CARD','PRIVATE_SENT_CONFIRMED')
NEW=('MAX_OUTSTANDING=20','MAX_OUTSTANDING_PRIVATE_CARDS_20','news_rg_wrong_photo_supersession_v1')
def err(s):raise RuntimeError(s)
def check():
 if os.geteuid()!=0:err('SUDO_REQUIRED')
 if O.is_symlink() or not O.is_dir():err('UNSAFE_OPERATOR')
 for p in (DST,SRC,O/'news_rg_wrong_photo_supersession_v1.py',O/'news_rg_durable_private_sender_v1.py'):
  if p.is_symlink() or not p.is_file():err('MISSING_OR_UNSAFE_'+p.name)
 old=DST.read_bytes();new=SRC.read_bytes()
 if len(old)>40000 or len(new)>40000:err('SIZE_LIMIT')
 o=old.decode('utf8');n=new.decode('utf8')
 if any(x not in n for x in NEW):err('UNKNOWN_NEW_VERSION')
 if 'getUpdates(' in n or 'sendPhoto(' in n or 'sendVideo(' in n:err('FORBIDDEN_ACTION')
 if old==new:return {'status':'ALREADY_UPGRADED','telegram_calls':0,'publications':0},None
 if any(x not in o for x in NEEDED):err('LIVE_VERSION_CHANGED')
 env=dict(os.environ);env['PYTHONPATH']=str(O)+os.pathsep+env.get('PYTHONPATH','')
 test=subprocess.run(['/usr/bin/python3',str(SRC),'selftest'],capture_output=True,text=True,timeout=15,env=env)
 if test.returncode or 'SELFTEST_PASS' not in test.stdout:err('NEW_SELFTEST_FAILED')
 return {'status':'READY','old_sha256':hashlib.sha256(old).hexdigest()[:16]},(old,new)
def install():
 report,pair=check()
 if pair is None:return report
 old,new=pair
 backup=O/('news_rg_dispatch_before_20_'+hashlib.sha256(old).hexdigest()[:16]+'.py')
 if backup.exists() or backup.is_symlink():err('BACKUP_EXISTS_STOP')
 fd,tmp=tempfile.mkstemp(prefix='.newsrg_backup_',dir=str(O))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),0o600);f.write(old);f.flush();os.fsync(f.fileno())
  os.link(tmp,backup)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 if DST.read_bytes()!=old:err('CONCURRENT_CHANGE')
 mode=stat.S_IMODE(DST.stat().st_mode)
 uid,gid=DST.stat().st_uid,DST.stat().st_gid
 fd,tmp=tempfile.mkstemp(prefix='.newsrg_dispatch_',dir=str(O))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),uid,gid)
   f.write(new);f.flush();os.fsync(f.fileno())
  os.replace(tmp,DST)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 try:
  t=subprocess.run(['/usr/bin/python3',str(DST),'selftest'],capture_output=True,text=True,timeout=15)
  if t.returncode or 'SELFTEST_PASS' not in t.stdout:err('LIVE_SELFTEST_FAILED')
 except Exception:
  fd,tmp=tempfile.mkstemp(dir=str(O))
  try:
   with os.fdopen(fd,'wb') as f:
    os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),uid,gid);f.write(old);f.flush();os.fsync(f.fileno())
   os.replace(tmp,DST)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  raise
 return {'status':'DISPATCH_20_INSTALLED','backup':str(backup),'new_pollers':0,'publications':0,'telegram_calls':0,'scheduler_changed':False}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:print('NEWS_RG_DISPATCH_20_UPGRADE_SELFTEST_PASS')
  elif sys.argv[1:]==['preflight']:print(json.dumps(check()[0]))
  elif sys.argv[1:]==['install']:print(json.dumps(install()))
  else:err('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100] if isinstance(e,RuntimeError) else type(e).__name__,'publications':0}));sys.exit(2)
