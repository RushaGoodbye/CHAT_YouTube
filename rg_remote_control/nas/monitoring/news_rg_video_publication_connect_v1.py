#!/usr/bin/env python3
"""Install NAS watermarked video into existing NEWS RG publication schedule.
No sends, getUpdates, new pollers or new DSM jobs during install. Fail closed.
"""
import os,sys,ast,pathlib,json,stat,tempfile,hashlib,subprocess
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
S=O/'news_rg_publication_schedule_v1.py'
V=O/'news_rg_approved_video_publication_v1.py'
ST=pathlib.Path('/tmp/news_rg_approved_video_publication_v1.py')
MARK='# NEWS_RG_APPROVED_VIDEO_PUBLICATION_ROUTE_V1'
OLD="  if obj.get('status')!='ACTIVE' or obj.get('new_approved_ready') is not True:return"
NEW="""  # NEWS_RG_APPROVED_VIDEO_PUBLICATION_ROUTE_V1
  target=P
  if obj.get('status')!='ACTIVE':return
  if obj.get('new_approved_ready') is not True:
   candidate=O/'news_rg_approved_video_publication_v1.py'
   if not candidate.is_file() or candidate.is_symlink():return
   v=subprocess.run(['/usr/bin/python3',str(candidate),'status'],
     capture_output=True,text=True,timeout=10)
   if v.returncode:return
   try:video_status=json.loads(v.stdout)
   except (TypeError,ValueError):return
   if video_status.get('status')!='VIDEO_PUBLISHER_ARMED' or video_status.get('approved_rendered_video_ready') is not True:return
   target=candidate"""
OLD2="proc=subprocess.Popen(['/usr/bin/python3',str(P),'publish-one'],"
NEW2="proc=subprocess.Popen(['/usr/bin/python3',str(target),'publish-one'],"
def fail(s):raise RuntimeError(s)
def write(p,blob,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_video_install_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),mode);f.write(blob);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(p))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def prepare():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 for p in (S,ST,O/'news_rg_approved_publication_v1.py',O/'news_rg_nas_video_pipeline_v1.py'):
  if not p.is_file() or p.is_symlink():fail('MISSING_OR_UNSAFE_'+p.name)
 orig=S.read_text('utf8');video=ST.read_text('utf8')
 ast.parse(orig);ast.parse(video)
 if 'NEWS_RG_VIDEO_PUBLISHER_SELFTEST_PASS' not in video or "PUBLIC_SEND_UNCERTAIN_NO_RETRY" not in video or "sendVideo" not in video:fail('VIDEO_SOURCE_NOT_RECOGNIZED')
 if MARK in orig:
  if OLD in orig:fail('PARTIAL_INSTALLATION')
  if not V.is_file() or V.is_symlink() or V.read_text('utf8')!=video:fail('EXISTING_VIDEO_VERSION_DIFFERS')
  return orig,orig,video,True
 if orig.count(OLD)!=1 or orig.count(OLD2)!=1:fail('SCHEDULER_LAYOUT_CHANGED')
 if 'news_rg_publication_last_launch' not in orig or 'fcntl.flock' not in orig or "'publish-one'" not in orig:fail('SCHEDULER_SAFETY_CONTRACT_MISSING')
 patched=orig.replace(OLD,NEW,1).replace(OLD2,NEW2,1)
 ast.parse(patched)
 p=subprocess.run(['/usr/bin/python3',str(ST),'selftest'],capture_output=True,text=True,timeout=12)
 if p.returncode or 'SELFTEST_PASS' not in p.stdout:fail('VIDEO_SELFTEST_FAILED')
 return orig,patched,video,False
def install():
 before,after,video,done=prepare()
 if done:return {'status':'VIDEO_PUBLICATION_ALREADY_CONNECTED','telegram_calls':0,'publications':0}
 if V.exists() or V.is_symlink():fail('LIVE_VIDEO_FILE_ALREADY_EXISTS')
 digest=hashlib.sha256(before.encode('utf8')).hexdigest()[:16]
 backup=O/('news_rg_pub_schedule_before_video_'+digest+'.py')
 if backup.exists() or backup.is_symlink():fail('BACKUP_EXISTS')
 with backup.open('xb') as f:f.write(before.encode('utf8'));f.flush();os.fsync(f.fileno())
 os.chmod(backup,0o600)
 mode=stat.S_IMODE(S.stat().st_mode)
 try:
  if S.read_text('utf8')!=before:fail('CONCURRENT_SCHEDULE_CHANGE')
  write(V,video.encode('utf8'),0o600)
  write(S,after.encode('utf8'),mode)
  if MARK not in S.read_text('utf8'):fail('POSTINSTALL_MISMATCH')
  test=subprocess.run(['/usr/bin/python3',str(V),'selftest'],capture_output=True,text=True,timeout=12)
  if test.returncode:fail('POSTINSTALL_SELFTEST_FAILED')
 except Exception:
  write(S,before.encode('utf8'),mode)
  if V.is_file() and not V.is_symlink():V.unlink()
  raise
 return {'status':'APPROVED_VIDEO_CONNECTED_TO_EXISTING_SCHEDULE','backup':str(backup),'new_dsm_tasks':0,'new_pollers':0,'telegram_calls':0,'publications':0,'photo_route_preserved':True}
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   ast.parse('def x():\n '+OLD+'\n')
   print('NEWS_RG_VIDEO_PUBLICATION_INSTALLER_SELFTEST_PASS')
  elif sys.argv[1:]==['preflight']:
   _,_,_,done=prepare();print(json.dumps({'status':'ALREADY_CONNECTED' if done else 'PREFLIGHT_PASS','publications':0}))
  elif sys.argv[1:]==['install']:print(json.dumps(install(),sort_keys=True))
  else:fail('INVALID_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:130],'publications':0}));sys.exit(2)
