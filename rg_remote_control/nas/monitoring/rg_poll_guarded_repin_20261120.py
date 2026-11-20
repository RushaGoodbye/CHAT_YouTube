#!/usr/bin/env python3
"""RG NEWS2: one-transaction V6 poll safety repair + pinned-release refresh.
No Telegram/publication, no new cron or pollers. Must run as root.
This retains the existing guarded self-healing integrity system.
"""
import datetime, fcntl, hashlib, io, json, os, pathlib, runpy, stat, sys, tarfile, tempfile, time
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
S=O/'../rg_news2_fix_20261119/protected_backups'
P=O/'news_rg_poll_moderation_v1.py'
Q=O/'news_rg_poll_quality_v1.py'
GUARD=O/'news_rg_guarded_release_v1.py'
META=R/'pinned_release_v1.json'
LOCK=R/'release.lock'
V6=pathlib.Path('/tmp/rg_poll_v6.py')
ORIGINAL='b29d6fa26ec32e77ee51bfd51b1d99b1cb88110def57adb6204de2a14bd4501a'
SAFE='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
QUALITY='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22'
GUARD_SHA='d8f7c97270827d3f39e5f8006a39d73632bc3b012e5218525e796e75f251c9c9'
TARGET='news_rg_poll_moderation_v1.py'
def sha(data):return hashlib.sha256(data).hexdigest()
def check(condition,reason):
 if not condition:raise RuntimeError(reason)
def atomic(path,data,mode=0o600):
 fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix='.rg_poll_repin_')
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,str(path))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def backup(path,data):
 fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def inspect_archive(path,keys,expected):
 check(path.is_file() and not path.is_symlink(),'PINNED_ARCHIVE_UNSAFE')
 with tarfile.open(str(path),'r:gz') as tf:
  members=tf.getmembers()
  check(len(members)==len(keys) and set(m.name for m in members)==set(keys),'PINNED_ARCHIVE_CONTENT_MISMATCH')
  for m in members:
   check(m.isfile() and m.size<2000000 and '/' not in m.name,'PINNED_ARCHIVE_MEMBER_UNSAFE')
   data=tf.extractfile(m).read()
   check(sha(data)==expected.get(m.name),'PINNED_ARCHIVE_SHA_MISMATCH_'+m.name)
def make_archive(path,keys):
 fd,name=tempfile.mkstemp(dir=str(path.parent),prefix='.rg_poll_archive_',suffix='.tar.gz')
 os.close(fd)
 try:
  with tarfile.open(name,'w:gz') as tf:
   for k in keys:
    p=O/k
    check(p.is_file() and not p.is_symlink(),'FILE_UNSAFE_'+k)
    info=tf.gettarinfo(str(p),arcname=k)
    info.uid=0;info.gid=0;info.uname='';info.gname=''
    with open(p,'rb') as f:tf.addfile(info,f)
  os.chmod(name,0o600)
  with tarfile.open(name,'r:gz') as tf:
   check(set(tf.getnames())==set(keys),'ARCHIVE_WRITE_TEST_FAILED')
  os.replace(name,str(path))
 finally:
  if os.path.exists(name):os.unlink(name)
def run():
 check(os.geteuid()==0,'ROOT_REQUIRED')
 for d in (O,R,S):
  check(d.is_dir() and not d.is_symlink(),'UNSAFE_DIRECTORY')
 for p in (P,Q,GUARD,V6,META):
  check(p.is_file() and not p.is_symlink(),'UNSAFE_FILE_'+p.name)
 check(sha(GUARD.read_bytes())==GUARD_SHA,'GUARDED_RELEASE_SCRIPT_CHANGED')
 check(sha(Q.read_bytes())==QUALITY,'POLL_QUALITY_MODULE_CHANGED')
 # Use the V6 patcher ONLY for the known original code; it never sends messages.
 source=runpy.run_path(str(V6))
 check(callable(source.get('make_patch')),'V6_PATCHER_MISSING')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR,0o600)
 fcntl.flock(fd,fcntl.LOCK_EX)
 stage='preflight'
 backup_prefix=None
 previous_source=P.read_bytes()
 mode=stat.S_IMODE(P.stat().st_mode)
 metadata_raw=META.read_bytes()
 old_archive=None
 new_archive=None
 try:
  meta=json.loads(metadata_raw)
  keys=tuple(runpy.run_path(str(GUARD))['KEY'])
  check(meta.get('schema')=='RG_NEWS_STABILITY_RELEASE_V1','PINNED_SCHEMA_CHANGED')
  expected=meta.get('files')
  check(isinstance(expected,dict) and set(keys)==set(expected),'PINNED_FILE_SET_CHANGED')
  check(TARGET in keys,'POLL_NOT_IN_RELEASE')
  old_archive=pathlib.Path(meta['last_known_good_archive'])
  check(str(old_archive.parent)==str(R),'ARCHIVE_OUTSIDE_RELEASE_DIRECTORY')
  check(sha(previous_source) in (ORIGINAL,SAFE),'UNEXPECTED_POLL_VERSION_SAFE_STOP')
  check(expected[TARGET]==ORIGINAL,'PINNED_POLL_ALREADY_DIFFERENT')
  check(mode==0o600,'POLL_FILE_MODE_CHANGED')
  inspect_archive(old_archive,keys,expected)
  for k in keys:
   p=O/k
   check(p.is_file() and not p.is_symlink(),'RELEASE_FILE_UNSAFE_'+k)
   if k!=TARGET:
    check(sha(p.read_bytes())==expected[k],'OTHER_MODULE_DRIFT_'+k)
  if sha(previous_source)==ORIGINAL:
   patched=source['make_patch'](previous_source.decode('utf8'))[0].encode('utf8')
   check(sha(patched)==SAFE,'V6_PATCH_OUTPUT_UNEXPECTED')
  else:patched=previous_source
  check('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' in patched.decode('utf8'),'PUBLICATION_GATE_MISSING')
  check(sha(patched)==SAFE,'PATCHED_SOURCE_SHA_UNEXPECTED')
  stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  recovery_dir=S/('poll_guarded_repin_'+stamp)
  recovery_dir.mkdir(mode=0o700)
  check(not recovery_dir.is_symlink(),'BACKUP_DIRECTORY_UNSAFE')
  backup(recovery_dir/'poll_previous.py',previous_source)
  backup(recovery_dir/'pinned_release_previous.json',metadata_raw)
  backup(recovery_dir/'old_archive_location.txt',str(old_archive).encode('utf8'))
  stage='live-patch'
  if sha(previous_source)!=SAFE:atomic(P,patched,mode)
  check(sha(P.read_bytes())==SAFE,'LIVE_PATCH_WRITE_FAILED')
  # Old acceptance suite runs under release lock, before approving the new pin.
  stage='acceptance'
  release=runpy.run_path(str(GUARD))
  release['acceptance']()
  stage='archive'
  new_archive=R/('last_known_good_poll_v6_'+stamp+'.tar.gz')
  check(not new_archive.exists(),'NEW_ARCHIVE_ALREADY_EXISTS')
  make_archive(new_archive,keys)
  fresh=dict(expected);fresh[TARGET]=SAFE
  inspect_archive(new_archive,keys,fresh)
  newmeta=dict(meta)
  newmeta['last_known_good_archive']=str(new_archive)
  newmeta['prior_archive']=str(old_archive)
  newmeta['installed_at']=int(time.time())
  newmeta['files']=fresh
  newmeta['acceptance']='PASS'
  newmeta['poll_safety']='RG_POLL_V6_PINNED_PAUSED_PUBLICATION'
  newmeta['poll_safety_at']=stamp
  stage='pin-update'
  atomic(META,(json.dumps(newmeta,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
  check(json.loads(META.read_text('utf8'))['files'][TARGET]==SAFE,'NEW_PIN_VERIFY_FAILED')
  # Explicitly verify all modules remain on the pinned release.
  status=release['status']()
  check(status.get('status')=='PINNED_STABLE','PIN_STATUS_FAILED')
  return {'status':'RG_NEWS2_POLL_V6_PERMANENT_PIN_PASS',
   'live_sha256':sha(P.read_bytes()),'pinned_archive':str(new_archive),
   'previous_archive':str(old_archive),'recovery_dir':str(recovery_dir),
   'release_integrity':status.get('status'),'modules_verified':len(keys),
   'quality_gate':True,'public_send_enabled':False,'telegram_calls':0,
   'publications':0,'second_pollers':0}
 except Exception:
  # Restore original live code + metadata; NEVER run release restoration on other modules.
  if stage!='preflight':
   try:
    atomic(P,previous_source,mode)
    atomic(META,metadata_raw)
   except Exception:pass
  raise
 finally:
  os.close(fd)
def selftest():
 import ast
 code=V6.read_text('utf8') if V6.exists() else ''
 check('def make_patch(' in code,'V6_MODULE_NOT_DOWNLOADED')
 check('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' in code,'V6_GATE_MISSING')
 print(json.dumps({'status':'RG_NEWS2_POLL_REPIN_INSTALLER_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if '--selftest' in sys.argv:selftest()
  else:print(json.dumps(run(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_NEWS2_POLL_REPIN_SAFE_STOP','phase':locals().get('stage','unknown'),
    'reason':str(e)[:180],'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
