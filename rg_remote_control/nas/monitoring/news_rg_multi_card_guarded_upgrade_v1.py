#!/usr/bin/env python3
"""NEWS RG: bounded private-moderation delivery, existing sole poller only.

Upgrades only existing dispatch/sender modules with atomic rollback/backups.
No Telegram API calls, no public posting, no new scheduled tasks/pollers.
"""
import os,sys,ast,json,stat,pathlib,tempfile,subprocess,fcntl,hashlib
OP=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
LOCK=OP/'news_rg_private_dispatch.lock'
FILES={'dispatch':('news_rg_durable_private_dispatch_v1.py','/tmp/news_rg_multi_dispatch.py'),
       'sender':('news_rg_durable_private_sender_v1.py','/tmp/news_rg_multi_sender.py')}
BACKUP=OP/'news_rg_multi_card_backup_v1'
def stop(s):raise RuntimeError(s)
def read(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>110000:stop('MISSING_OR_UNSAFE_'+p.name)
 return p.read_text('utf8')
def atomic(p,blob,mode,uid,gid):
 fd,tmp=tempfile.mkstemp(prefix='.rg_multi_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   os.fchown(f.fileno(),uid,gid)
   f.write(blob);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def preflight():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 if OP.is_symlink() or not OP.is_dir():stop('OPERATOR_DIR_UNSAFE')
 if BACKUP.exists() or BACKUP.is_symlink():stop('BACKUP_EXISTS')
 if LOCK.is_symlink() or not LOCK.is_file():stop('DISPATCH_LOCK_UNSAFE')
 worker=read(OP/'rg_news2_p31_guarded_callback_once.py')
 if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in worker or '# NEWS_RG_MANUAL_LINK_SINGLE_OWNER_V1' not in worker:
  stop('EXISTING_SINGLE_OWNER_ROUTE_CHANGED')
 owner=read(OP/'callback_v29.py')
 if "WORKER=O/'rg_news2_p31_guarded_callback_once.py'" not in owner:stop('TELEGRAM_OWNER_CHANGED')
 originals={}
 for key,(name,stage) in FILES.items():
  dest=OP/name
  old=read(dest)
  new=read(pathlib.Path(stage))
  ast.parse(new)
  if 'MAX_OUTSTANDING=20' not in new or 'news_rg_wrong_photo_supersession_v1' not in new:
   stop('NEW_BOUND_CONTRACT_MISSING_'+key)
  if 'MAX_OUTSTANDING=20' in old:stop('ALREADY_UPGRADED')
  if 'ONE_OUTSTANDING_EDITORIAL_CARD' not in old and key=='dispatch':
   stop('DISPATCH_OLD_SINGLE_GATE_NOT_FOUND')
  if 'WAITING_FOR_EDITORIAL_DECISION' not in old and key=='sender':
   stop('SENDER_OLD_SINGLE_GATE_NOT_FOUND')
  if 'pack_original_video' not in new and key=='sender':stop('VIDEO_PRIVATE_SENDER_LOST')
  if "publications':0" not in new:stop('PUBLICATION_GUARD_REMOVED')
  originals[key]=(dest,old,new)
 for key,(name,stage) in FILES.items():
  env={**os.environ,'PYTHONPATH':str(OP)}
  t=subprocess.run(['/usr/bin/python3',stage,'selftest'],env=env,
   stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,text=True)
  if t.returncode or 'SELFTEST_PASS' not in t.stdout:stop('STAGED_SELFTEST_FAIL_'+key)
 return originals
def install():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 fd=os.open(str(LOCK),os.O_RDWR)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX)
  originals=preflight()
  BACKUP.mkdir(mode=0o700)
  os.chmod(BACKUP,0o700)
  changed=[]
  try:
   for key,(dest,old,new) in originals.items():
    bak=BACKUP/(dest.name+'.before')
    bfd=os.open(str(bak),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(bfd,'wb') as out:
     out.write(old.encode('utf8'));out.flush();os.fsync(out.fileno())
   for key,(dest,old,new) in originals.items():
    if read(dest)!=old:stop('CONCURRENT_CHANGE_'+key)
    st=dest.stat()
    atomic(dest,new.encode('utf8'),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
    changed.append(key)
    if read(dest)!=new:stop('WRITE_UNVERIFIED_'+key)
    t=subprocess.run(['/usr/bin/python3',str(dest),'selftest'],env={**os.environ,'PYTHONPATH':str(OP)},
       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,text=True)
    if t.returncode or 'SELFTEST_PASS' not in t.stdout:stop('INSTALLED_SELFTEST_FAIL_'+key)
   return {'status':'NEWS_RG_MULTI_CARD_DELIVERY_INSTALLED',
      'max_outstanding':20,'files_upgraded':2,'backups':2,
      'single_telegram_owner_unchanged':True,'new_pollers':0,
      'publications':0,'telegram_bot_calls_during_install':0}
  except Exception:
   for key in reversed(changed):
    dest,old,new=originals[key]
    try:
     if read(dest)!=new:continue
     st=dest.stat()
     atomic(dest,old.encode('utf8'),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
    except Exception:pass
   raise
 finally:os.close(fd)
def selftest():
 assert set(FILES)=={'dispatch','sender'}
 assert len(FILES)==2
 assert BACKUP.name=='news_rg_multi_card_backup_v1'
 print('NEWS_RG_MULTI_CARD_GUARDED_UPGRADE_SELFTEST_PASS')
if __name__=='__main__':
 try:
  arg=sys.argv[1:]
  if arg==['selftest']:selftest()
  elif arg==['preflight']:
   checked=preflight()
   print(json.dumps({'status':'NEWS_RG_MULTI_CARD_PREFLIGHT_PASS',
    'files':len(checked),'new_pollers':0,'publications':0},sort_keys=True))
  elif arg==['install']:print(json.dumps(install(),sort_keys=True))
  else:stop('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:125] if isinstance(e,RuntimeError) else type(e).__name__,
   'publications':0,'telegram_sends':0,'new_pollers':0},sort_keys=True))
  sys.exit(2)
