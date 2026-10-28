#!/usr/bin/env python3
"""Upgrade the EXISTING private dispatch and callback checks for one invalid photo.

Only staged/sent photo for https://t.me/nexta_live/125698 may be system
superseded by its already staged source video. No human decision is fabricated.
No Telegram calls, publications, new pollers, scheduler changes or DB edits.
"""
import os,sys,json,stat,pathlib,subprocess,tempfile,ast
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
STAGE={
 'helper':('/tmp/news_rg_supersession_helper.py','news_rg_wrong_photo_supersession_v1.py'),
 'dispatch':('/tmp/news_rg_supersession_dispatch.py','news_rg_durable_private_dispatch_v1.py'),
 'sender':('/tmp/news_rg_supersession_sender.py','news_rg_durable_private_sender_v1.py'),
 'callback':('/tmp/news_rg_supersession_callback.py','news_rg_editorial_callbacks_v1.py'),
}
BACKUP=O/'news_rg_wrong_photo_gate_backup_v1'
def die(msg):raise RuntimeError(msg)
def safe_read(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>110000:die('UNSAFE_OR_MISSING_'+p.name)
 return p.read_text('utf8')
def atomic(p,data,mode,uid,gid):
 fd,tmp=tempfile.mkstemp(prefix='.newsrg_photo_recovery_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),uid,gid)
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def checked():
 if os.geteuid()!=0:die('SUDO_REQUIRED')
 if O.is_symlink() or not O.is_dir():die('OPERATOR_PATH_UNSAFE')
 if BACKUP.exists() or BACKUP.is_symlink():die('BACKUP_CONFLICT')
 worker=safe_read(O/'rg_news2_p31_guarded_callback_once.py')
 if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in worker or '# NEWS_RG_MANUAL_LINK_SINGLE_OWNER_V1' not in worker:
  die('ONE_TELEGRAM_OWNER_CONTRACT_CHANGED')
 owner=safe_read(O/'callback_v29.py')
 if "WORKER=O/'rg_news2_p31_guarded_callback_once.py'" not in owner:
  die('TELEGRAM_OWNER_CHANGED')
 items={}
 for key,(src,destname) in STAGE.items():
  source=pathlib.Path(src);new=safe_read(source);ast.parse(new)
  dest=O/destname
  old=None if key=='helper' and not dest.exists() else safe_read(dest)
  if key=='helper' and old is not None:die('SUPERSESSION_HELPER_ALREADY_PRESENT')
  if key!='helper' and ('news_rg_wrong_photo_supersession_v1' in old):
   die('SUPERSESSION_ALREADY_INSTALLED')
  if key!='helper' and ('news_rg_wrong_photo_supersession_v1' not in new):
   die('PATCH_MISSING_SUPERSESSION_'+key)
  items[key]=(dest,old,new)
 if 'def is_superseded' not in items['helper'][2] or 'def install_one' not in items['helper'][2]:
  die('UNRECOGNIZED_SUPERSESSION_HELPER')
 if 'ONE_OUTSTANDING_EDITORIAL_CARD' not in items['dispatch'][1]:
  die('DISPATCH_GATE_CHANGED')
 if 'def pack_original_video' not in items['sender'][1] or 'sendVideo' not in items['sender'][1]:
  die('ORIGINAL_VIDEO_SENDER_UNVERIFIED')
 if 'def _watermark_after_video_accept' not in items['callback'][1]:
  die('EXISTING_VIDEO_EDITORIAL_CALLBACK_CHANGED')
 # Run exact-post read-only preflight before installing anything.
 pre=subprocess.run(['/usr/bin/python3',STAGE['helper'][0],'preflight'],
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=12)
 if pre.returncode:
  try:detail=json.loads(pre.stdout).get('reason','UNKNOWN')
  except ValueError:detail='INVALID_PREFLIGHT_RESULT'
  die('WRONG_PHOTO_PREFLIGHT_'+str(detail)[:85])
 if 'WRONG_PHOTO_SAFE_SUPERSESSION_ELIGIBLE' not in pre.stdout:
  die('WRONG_PHOTO_NOT_ELIGIBLE')
 return items
def install():
 items=checked()
 BACKUP.mkdir(mode=0o700)
 os.chmod(BACKUP,0o700)
 changed=[]
 try:
  for key in ('dispatch','sender','callback'):
   dest,old,_=items[key]
   bak=BACKUP/(dest.name+'.before')
   with bak.open('xb') as out:
    os.fchmod(out.fileno(),0o600)
    out.write(old.encode('utf8'));out.flush();os.fsync(out.fileno())
   if safe_read(dest)!=old:die('CONCURRENT_CHANGE_'+key)
  for key in ('helper','callback','sender','dispatch'):
   dest,old,new=items[key]
   if key=='helper' and (dest.exists() or dest.is_symlink()):
    die('CONCURRENT_SUPERSESSION_HELPER')
   if key=='helper':
    st=O.stat()
    atomic(dest,new.encode('utf8'),0o600,st.st_uid,st.st_gid)
   else:
    st=dest.stat()
    atomic(dest,new.encode('utf8'),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
   changed.append(key)
   if safe_read(dest)!=new:die('WRITE_NOT_VERIFIED_'+key)
   ret=subprocess.run(['/usr/bin/python3','-m','py_compile',str(dest)],
     capture_output=True,timeout=9)
   if ret.returncode:die('LIVE_COMPILE_FAILED_'+key)
  t=subprocess.run(['/usr/bin/python3',str(items['helper'][0]),'selftest'],
    capture_output=True,text=True,timeout=12)
  if t.returncode or 'SELFTEST_PASS' not in t.stdout:
   die('SUPERSESSION_LIVE_SELFTEST_FAILED')
  return {'status':'WRONG_PHOTO_SAFE_GATE_INSTALLED',
   'backups':3,'telegram_update_owner_untouched':True,
   'old_photo_not_yet_superseded':True,'publications':0,'new_pollers':0,
   'no_human_decision_fabricated':True}
 except Exception:
  for key in reversed(changed):
   dest,old,new=items[key]
   try:
    if key=='helper':
     if dest.is_file() and not dest.is_symlink() and safe_read(dest)==new:dest.unlink()
    elif dest.is_file() and not dest.is_symlink() and safe_read(dest)==new:
     st=dest.stat()
     atomic(dest,old.encode('utf8'),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
   except (OSError,RuntimeError):pass
  raise
def selftest():
 assert len(STAGE)==4
 assert set(STAGE)=={'helper','dispatch','sender','callback'}
 print('NEWS_RG_WRONG_PHOTO_GATE_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:
   checked()
   print(json.dumps({'status':'WRONG_PHOTO_GATE_PREFLIGHT_PASS','pollers':0,'publications':0},sort_keys=True))
  elif sys.argv[1:]==['install']:
   print(json.dumps(install(),sort_keys=True))
  else:die('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:130] if isinstance(e,RuntimeError) else type(e).__name__,
    'publications':0,'telegram_bot_calls':0,'new_pollers':0},sort_keys=True))
  sys.exit(2)
