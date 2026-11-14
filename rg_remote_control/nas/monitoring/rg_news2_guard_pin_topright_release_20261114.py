#!/usr/bin/env python3
"""NEWS2 guarded-release pin of approved Nov 14 watermark update.

One exact operation: change 2026-11-05 stable guard's two old hashes to
already-installed user-approved renderer/publisher and create a full verified
immutable 18-file LKG archive. Does NOT change operational Python sources,
send Telegram messages, call Cloudflare, start workers or poll updates.

Root-only, fail-closed, guarded by same flock as existing stability tick.
Backup and rollback on exception. No arbitrary input paths.
"""
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
STATE=R/'pinned_release_v1.json'
GUARD_LOCK=R/'release.lock'
RENDER='news_rg_nas_video_pipeline_v1.py'
PUBLISH='news_rg_approved_video_publication_v1.py'
OLD_RENDER='59b87da6057482702807837948da46307396fc4e63e2a2fc7c181ec692c10e55'
OLD_PUBLISH='7a3fdfdd443803834c0da18a05d3a5cde512ed34322e64bce89255d68a6dd395'
NEW_RENDER='b37c7582954bc301efdf94bb0c42233daa9c4676fc28cfc6ec5a5ec6a4996c67'
NEW_PUBLISH='ec531215193d5caa184797ad298d00936df1265e16c0aed1affdb96f4c116679'
OLD_VERSION='2026-11-05-stable5.1-python315'
NEW_VERSION='2026-11-14-stable5.2-topright-watermark'
PROFILE=O/'assets/approved_watermark_profile_20261114.json'
LOGO=O/'assets/rg_approved_watermark_20261104.png'
LOGO_SHA='1e852e8540d079ebf275294a784559557098dab455f14bcfa1efe86152b73585'
RELEASE_NAME='RG_NEWS2_WM_GUARD_PIN_20261114'
RELEASE_DIR=R/'pin_topright_watermark_20261114'
BACKUP=RELEASE_DIR/'pinned_release_before.json'
RECEIPT=RELEASE_DIR/'receipt.json'
NEW_ARCHIVE=RELEASE_DIR/'last_known_good_topright.tar.gz'
KEY=('news_rg_manual_link_intake_v1.py',
'news_rg_editorial_callbacks_v1.py',
'news_rg_approved_text_publication_v1.py',
'news_rg_durable_private_sender_v1.py',
'news_rg_durable_private_dispatch_v1.py',
'news_rg_stability_healthcheck_v1.py',
'news_rg_continuous_callback_v1.py',
'news_rg_publication_schedule_v1.py',
'news_rg_editorial_rank_v1.py',
RENDER,
'news_rg_stable5_operational_gate_v1.py',
'news_rg_autonomous_health_v1.py',
'news_rg_release_acceptance_v1.py',
'news_rg_source_shadow_ingest_v1.py',
PUBLISH,
'news_rg_video_watermark_handoff_v1.py',
'news_rg_nas_video_schedule_v1.py',
'news_rg_editorial_ai_gate_v1.py')
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def safe_file(p,limit=20000000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size<1 or st.st_size>limit or st.st_mode&0o022:
  raise Stop('UNSAFE_FILE_'+p.name)
 return p.read_bytes()
def root_dir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_DIR_'+p.name)
def atomic(p,b,mode=0o600):
 fd,tmp=tempfile.mkstemp(prefix='.rg_pin_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def expected_actual():
 root_dir(O);root_dir(R)
 raw=safe_file(STATE,50000)
 original=json.loads(raw)
 if original.get('schema')!='RG_NEWS_STABILITY_RELEASE_V1' or original.get('version')!=OLD_VERSION:
  raise Stop('PINNED_VERSION_CHANGED')
 expected=original.get('files')
 if not isinstance(expected,dict) or set(expected)!=set(KEY):raise Stop('PINNED_COMPONENT_SET_CHANGED')
 if expected.get(RENDER)!=OLD_RENDER or expected.get(PUBLISH)!=OLD_PUBLISH:
  raise Stop('BASELINE_NOT_EXPECTED')
 results={}
 for name in KEY:
  b=safe_file(O/name,1000000)
  h=sha(b)
  want=NEW_RENDER if name==RENDER else NEW_PUBLISH if name==PUBLISH else expected[name]
  if h!=want:raise Stop('PRODUCTION_COMPONENT_DRIFT_'+name)
  results[name]=b
 profile=json.loads(safe_file(PROFILE,20000))
 if (profile.get('watermark_profile')!='RG_APPROVED_20261114_TOPRIGHT_040_078'
    or profile.get('position')!='top_right' or profile.get('scale_width')!=0.4
    or profile.get('alpha')!=0.78 or profile.get('margin_top')!=0.03
    or profile.get('margin_right')!=0.03 or profile.get('sha256')!=LOGO_SHA):
  raise Stop('USER_APPROVED_WATERMARK_PROFILE_MISMATCH')
 if sha(safe_file(LOGO,15000000))!=LOGO_SHA:raise Stop('LOGO_HASH_DRIFT')
 old_archive=Path(original.get('last_known_good_archive') or '')
 if not old_archive.is_file() or old_archive.is_symlink() or old_archive.parent!=R:
  raise Stop('ORIGINAL_LKG_ARCHIVE_UNSAFE')
 # Existing full baseline backup must be valid and consistent.
 with tarfile.open(old_archive,'r:gz') as tf:
  if set(tf.getnames())!=set(KEY):raise Stop('ORIGINAL_LKG_MEMBERS')
  for name in KEY:
   entry=tf.getmember(name)
   if not entry.isfile() or entry.size>1000000:raise Stop('ORIGINAL_LKG_ENTRY_UNSAFE')
   data=tf.extractfile(entry).read()
   if sha(data)!=expected[name]:raise Stop('ORIGINAL_LKG_CONTENT_DRIFT_'+name)
 return raw,original,results

def acceptance():
 # Runs existing release suite with pinned DSM Python 3.15, not Telegram sends.
 py=O/'tools/python-3.15.2/bin/python3.15'
 if py.is_symlink() or not py.is_file():raise Stop('PINNED_PYTHON_MISSING')
 test=O/'news_rg_release_acceptance_v1.py'
 v=subprocess.run([str(py),str(test)],capture_output=True,text=True,timeout=65)
 if v.returncode or 'NEWS_RG_RELEASE_ACCEPTANCE_PASS' not in v.stdout:
  raise Stop('RELEASE_ACCEPTANCE_FAILED')
 for module,token in ((RENDER,'NEWS_RG_NAS_VIDEO_PIPELINE_SELFTEST_PASS'),
                      (PUBLISH,'NEWS_RG_VIDEO_PUBLISHER_SELFTEST_PASS')):
  t=subprocess.run([str(py),str(O/module),'selftest'],capture_output=True,text=True,timeout=25)
  if t.returncode or token not in t.stdout:
   raise Stop('RENDER_OR_PUBLISH_SELFTEST_FAILED_'+module)
 return True

def create_archive(dst,data):
 # Creates tar only for exact fixed file list from verified in-memory bytes.
 fd,tmp=tempfile.mkstemp(prefix='.rg_guard_lkg_',dir=str(dst.parent),suffix='.tar.gz')
 os.close(fd)
 try:
  with tarfile.open(tmp,'w:gz') as tf:
   for name in KEY:
    raw=data[name]
    member=tarfile.TarInfo(name)
    member.mode=0o600
    member.uid=0;member.gid=0
    member.mtime=int(time.time())
    member.size=len(raw)
    tf.addfile(member,io.BytesIO(raw))
  os.chmod(tmp,0o600)
  with tarfile.open(tmp,'r:gz') as tf:
   if set(tf.getnames())!=set(KEY):raise Stop('NEW_LKG_MEMBERS_INVALID')
   for name in KEY:
    m=tf.getmember(name)
    if not m.isfile() or sha(tf.extractfile(m).read())!=sha(data[name]):
     raise Stop('NEW_LKG_MISMATCH_'+name)
  os.replace(tmp,dst)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def lock():
 if GUARD_LOCK.is_symlink():raise Stop('GUARD_LOCK_SYMLINK')
 fd=os.open(str(GUARD_LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 return fd

def apply():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 fd=lock()
 try:
  before,metadata,data=expected_actual()
  if any(p.exists() or p.is_symlink() for p in (RELEASE_DIR,NEW_ARCHIVE,BACKUP,RECEIPT)):
   raise Stop('RELEASE_DIR_ALREADY_EXISTS')
  acceptance()
  root_dir(RELEASE_DIR,create=True)
  atomic(BACKUP,before)
  if safe_file(BACKUP)!=before:raise Stop('PINNED_BACKUP_MISMATCH')
  create_archive(NEW_ARCHIVE,data)
  updated=dict(metadata)
  updated['version']=NEW_VERSION
  updated['installed_at']=int(time.time())
  updated['prior_archive']=metadata['last_known_good_archive']
  updated['last_known_good_archive']=str(NEW_ARCHIVE)
  updated['files']=dict(metadata['files'])
  updated['files'][RENDER]=NEW_RENDER
  updated['files'][PUBLISH]=NEW_PUBLISH
  updated['acceptance']='PASS'
  updated['watermark_release']=RELEASE_NAME
  updated['approved_watermark_profile']='RG_APPROVED_20261114_TOPRIGHT_040_078'
  blob=(json.dumps(updated,ensure_ascii=False,indent=2)+'\n').encode()
  try:
   atomic(STATE,blob)
   actual=json.loads(safe_file(STATE,50000))
   if (actual.get('version')!=NEW_VERSION or
     actual.get('last_known_good_archive')!=str(NEW_ARCHIVE) or
     actual['files'][RENDER]!=NEW_RENDER or actual['files'][PUBLISH]!=NEW_PUBLISH):
    raise Stop('PINNED_METADATA_POSTINSTALL_INVALID')
   acceptance()
   record={'status':'APPLIED_QA_PASS','release':RELEASE_NAME,
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'baseline_hash':sha(before),'new_pinned_hash':sha(blob),
    'archive_sha256':sha(safe_file(NEW_ARCHIVE,3000000)),
    'components_verified':len(KEY),'updated_components':[RENDER,PUBLISH],
    'old_center_receipts_rejected':True,
    'telegram_sends':0,'publications':0,'backup_verified':True}
   atomic(RECEIPT,(json.dumps(record,sort_keys=True)+'\n').encode())
   return record
  except Exception:
   atomic(STATE,before)
   if safe_file(STATE)!=before:raise Stop('PINNED_METADATA_ROLLBACK_FAILED')
   raise
 finally:
  os.close(fd)

def selftest():
 assert len(KEY)==18 and NEW_RENDER!=OLD_RENDER and NEW_PUBLISH!=OLD_PUBLISH
 assert len(NEW_RENDER)==len(NEW_PUBLISH)==64
 assert RELEASE_DIR.parent==R
 print('NEWS2_GUARD_PIN_TOPRIGHT_RELEASE_SELFTEST_PASS')

if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args==['preflight']:
   if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
   _,old,data=expected_actual()
   acceptance()
   print(json.dumps({'status':'PREFLIGHT_PASS','old_release':old['version'],
       'modules_verified':len(data),'telegram_sends':0,'publications':0}))
  elif args==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:150],
       'telegram_sends':0,'publications':0}))
  raise SystemExit(2)
