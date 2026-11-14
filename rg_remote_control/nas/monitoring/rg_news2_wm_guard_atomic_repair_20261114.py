#!/usr/bin/env python3
"""NEWS2 one-shot atomic repair of the watermark release AND its stable guard.

The Nov14 watermark modules were correctly installed, then the Nov05 LKG guard
restored the old modules. This installer fixes both in ONE transaction under
the EXISTING guard + video + publication locks. Fixed approved hashes only.

No Telegram/Cloudflare calls, no new pollers, no user data modification,
no public sends, no reload or restart of workers. Root-only.
"""
import datetime,fcntl,hashlib,io,json,os,re,stat,subprocess,sys,tarfile,tempfile,time
from pathlib import Path

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
STATE=R/'pinned_release_v1.json'
RENDER=O/'news_rg_nas_video_pipeline_v1.py'
PUBLISH=O/'news_rg_approved_video_publication_v1.py'
PROFILE=O/'assets/approved_watermark_profile_20261114.json'
LOGO=O/'assets/rg_approved_watermark_20261104.png'
OLD_R='59b87da6057482702807837948da46307396fc4e63e2a2fc7c181ec692c10e55'
OLD_P='7a3fdfdd443803834c0da18a05d3a5cde512ed34322e64bce89255d68a6dd395'
NEW_R='b37c7582954bc301efdf94bb0c42233daa9c4676fc28cfc6ec5a5ec6a4996c67'
NEW_P='ec531215193d5caa184797ad298d00936df1265e16c0aed1affdb96f4c116679'
LOGO_SHA='1e852e8540d079ebf275294a784559557098dab455f14bcfa1efe86152b73585'
OLD_VERSION='2026-11-05-stable5.1-python315'
NEW_VERSION='2026-11-14-stable5.2-topright-watermark'
OLD_ID='RG_APPROVED_20261104_CENTER_040_078'
NEW_ID='RG_APPROVED_20261114_TOPRIGHT_040_078'
OLD_OVERLAY='overlay=(W-w)/2:(H-h)/2:shortest=0:eof_action=repeat:repeatlast=1[v]'
NEW_OVERLAY='overlay=W-w-W*0.03:H*0.03:shortest=0:eof_action=repeat:repeatlast=1[v]'
OLD_ROI='crop=iw*0.38:ih*0.20:(iw-iw*0.38)/2:(ih-ih*0.20)/2'
NEW_ROI='crop=iw*0.44:ih*0.24:iw-iw*0.44:0'
REL=R/'guard_repair_wm_20261114'
BR=REL/'old_renderer.py'
BP=REL/'old_publisher.py'
BS=REL/'old_pinned_state.json'
NEW_ARCH=REL/'last_known_good_topright.tar.gz'
RECEIPT=REL/'receipt.json'
LOCKS=[R/'release.lock',O/'news_rg_nas_video_schedule.lock',
 O/'news_rg_nas_video_pipeline.lock',O/'news_rg_publication.lock']
KEY=('news_rg_manual_link_intake_v1.py','news_rg_editorial_callbacks_v1.py',
 'news_rg_approved_text_publication_v1.py','news_rg_durable_private_sender_v1.py',
 'news_rg_durable_private_dispatch_v1.py','news_rg_stability_healthcheck_v1.py',
 'news_rg_continuous_callback_v1.py','news_rg_publication_schedule_v1.py',
 'news_rg_editorial_rank_v1.py','news_rg_nas_video_pipeline_v1.py',
 'news_rg_stable5_operational_gate_v1.py','news_rg_autonomous_health_v1.py',
 'news_rg_release_acceptance_v1.py','news_rg_source_shadow_ingest_v1.py',
 'news_rg_approved_video_publication_v1.py','news_rg_video_watermark_handoff_v1.py',
 'news_rg_nas_video_schedule_v1.py','news_rg_editorial_ai_gate_v1.py')
class Stop(ValueError):pass
def sha(data):return hashlib.sha256(data).hexdigest()
def regular(p,expected=None,limit=3000000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or not 1<=st.st_size<=limit or st.st_mode&0o022:
  raise Stop('FILE_UNSAFE_'+p.name)
 b=p.read_bytes()
 if expected and sha(b)!=expected:raise Stop('FILE_HASH_DRIFT_'+p.name)
 return b
def rootdir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('DIRECTORY_UNSAFE_'+p.name)
def atomic(p,data,mode):
 fd,tmp=tempfile.mkstemp(prefix='.rg_news2_wm_guard_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def patch(src,old,new,count):
 if src.count(old)!=count:raise Stop('PATCH_SOURCE_DRIFT')
 return src.replace(old,new)
def expected_patches(old_r,old_p):
 r=old_r.decode('utf8');p=old_p.decode('utf8')
 r=patch(r,OLD_ID,NEW_ID,2)
 r=patch(r,OLD_OVERLAY,NEW_OVERLAY,1)
 r=patch(r,OLD_ROI,NEW_ROI,2)
 p=patch(p,OLD_ID,NEW_ID,1)
 r=r.encode();p=p.encode()
 if sha(r)!=NEW_R or sha(p)!=NEW_P:raise Stop('PATCHED_HASH_DIFFERENT')
 compile(r,'renderer_candidate.py','exec')
 compile(p,'publisher_candidate.py','exec')
 return r,p

def original_archive_ok(old_state):
 archive=Path(old_state['last_known_good_archive'])
 if archive.parent!=R or archive.is_symlink() or not archive.is_file():
  raise Stop('ORIGINAL_LKG_MISSING')
 with tarfile.open(archive,'r:gz') as tf:
  if set(tf.getnames())!=set(KEY):raise Stop('LKG_FILE_LIST_MISMATCH')
  for name in KEY:
   m=tf.getmember(name)
   if not m.isfile() or m.size>1000000:
    raise Stop('LKG_ENTRY_UNSAFE')
   if sha(tf.extractfile(m).read())!=old_state['files'][name]:
    raise Stop('ORIGINAL_LKG_CHECKSUM_MISMATCH_'+name)

def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 rootdir(O);rootdir(R)
 if any(p.is_symlink() for p in [*LOCKS,REL,BR,BP,BS,NEW_ARCH,RECEIPT]):
  raise Stop('SYMLINK_REJECTED')
 if REL.exists():raise Stop('RELEASE_ALREADY_ATTEMPTED')
 raw_state=regular(STATE,limit=60000)
 state=json.loads(raw_state)
 if state.get('version')!=OLD_VERSION or state.get('schema')!='RG_NEWS_STABILITY_RELEASE_V1':
  raise Stop('GUARD_BASELINE_CHANGED')
 wanted=state.get('files') or {}
 if set(wanted)!=set(KEY) or wanted.get(RENDER.name)!=OLD_R or wanted.get(PUBLISH.name)!=OLD_P:
  raise Stop('GUARD_COMPONENT_SET_CHANGED')
 current={}
 for name in KEY:
  actual=regular(O/name,limit=1200000)
  if sha(actual)!=wanted[name]:raise Stop('EXISTING_GUARD_BASELINE_NOT_RESTORED_'+name)
  current[name]=actual
 original_archive_ok(state)
 profile=json.loads(regular(PROFILE,limit=25000))
 if (profile.get('watermark_profile')!=NEW_ID or profile.get('position')!='top_right'
    or profile.get('scale_width')!=0.4 or profile.get('alpha')!=0.78
    or profile.get('margin_top')!=0.03 or profile.get('margin_right')!=0.03
    or profile.get('sha256')!=LOGO_SHA):
  raise Stop('USER_APPROVED_PROFILE_CHANGED')
 regular(LOGO,LOGO_SHA,limit=15000000)
 new_r,new_p=expected_patches(current[RENDER.name],current[PUBLISH.name])
 return raw_state,state,current,new_r,new_p

def test_patched_renderers(r,p):
 py=O/'tools/python-3.15.2/bin/python3.15'
 if not py.is_file() or py.is_symlink():raise Stop('PINNED_PYTHON_MISSING')
 # Existing script's selftest uses its own absolute metadata, while no
 # render, download, Telegram API or publication occurs in selftest mode.
 for name,blob,mark in (
    (RENDER.name,r,'NEWS_RG_NAS_VIDEO_PIPELINE_SELFTEST_PASS'),
    (PUBLISH.name,p,'NEWS_RG_VIDEO_PUBLISHER_SELFTEST_PASS')):
  with tempfile.TemporaryDirectory(prefix='rg_news2_wm_selftest_') as td:
   file=Path(td)/name;file.write_bytes(blob)
   result=subprocess.run([str(py),str(file),'selftest'],capture_output=True,text=True,timeout=25)
   if result.returncode or mark not in result.stdout:
    raise Stop('PATCHED_SELFTEST_FAILED_'+name)
 return True

def full_acceptance():
 py=O/'tools/python-3.15.2/bin/python3.15'
 script=O/'news_rg_release_acceptance_v1.py'
 result=subprocess.run([str(py),str(script)],capture_output=True,text=True,timeout=80)
 if result.returncode or 'NEWS_RG_RELEASE_ACCEPTANCE_PASS' not in result.stdout:
  raise Stop('NEWS_RG_RELEASE_ACCEPTANCE_FAILED')
 for name,mark in ((RENDER.name,'NEWS_RG_NAS_VIDEO_PIPELINE_SELFTEST_PASS'),
                   (PUBLISH.name,'NEWS_RG_VIDEO_PUBLISHER_SELFTEST_PASS')):
  t=subprocess.run([str(py),str(O/name),'selftest'],capture_output=True,text=True,timeout=25)
  if t.returncode or mark not in t.stdout:raise Stop('LIVE_SELFTEST_FAIL_'+name)

def create_lkg(dst,rows):
 fd,tmp=tempfile.mkstemp(prefix='.rg_news2_lkg_',dir=str(dst.parent),suffix='.tar.gz')
 os.close(fd)
 try:
  with tarfile.open(tmp,'w:gz') as tf:
   for name in KEY:
    data=rows[name]
    t=tarfile.TarInfo(name);t.mode=0o600;t.uid=t.gid=0
    t.mtime=int(time.time());t.size=len(data)
    tf.addfile(t,io.BytesIO(data))
  os.chmod(tmp,0o600)
  with tarfile.open(tmp,'r:gz') as tf:
   if set(tf.getnames())!=set(KEY):raise Stop('NEW_ARCHIVE_MEMBER_LIST')
   for name in KEY:
    member=tf.getmember(name)
    if not member.isfile() or sha(tf.extractfile(member).read())!=sha(rows[name]):
     raise Stop('NEW_ARCHIVE_HASH_INVALID_'+name)
  os.replace(tmp,dst)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def hold_locks():
 fds=[]
 try:
  for path in LOCKS:
   fd=os.open(str(path),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except Exception:os.close(fd);raise
   fds.append(fd)
  return fds
 except Exception:
  for fd in reversed(fds):os.close(fd)
  raise Stop('LIVE_PUBLISH_OR_GUARD_BUSY')

def apply():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 fds=hold_locks()
 try:
  raw_state,old_state,current,new_r,new_p=preflight()
  test_patched_renderers(new_r,new_p)
  rootdir(REL,create=True)
  atomic(BR,current[RENDER.name],0o600)
  atomic(BP,current[PUBLISH.name],0o600)
  atomic(BS,raw_state,0o600)
  regular(BR,OLD_R);regular(BP,OLD_P)
  if regular(BS)!=raw_state:raise Stop('GUARD_METADATA_BACKUP_MISMATCH')
  mode_r=stat.S_IMODE(RENDER.stat().st_mode)
  mode_p=stat.S_IMODE(PUBLISH.stat().st_mode)
  installed=False
  try:
   atomic(RENDER,new_r,mode_r)
   installed=True
   atomic(PUBLISH,new_p,mode_p)
   regular(RENDER,NEW_R);regular(PUBLISH,NEW_P)
   full_acceptance()
   rows=dict(current)
   rows[RENDER.name]=new_r
   rows[PUBLISH.name]=new_p
   create_lkg(NEW_ARCH,rows)
   next_state=dict(old_state)
   next_state['version']=NEW_VERSION
   next_state['installed_at']=int(time.time())
   next_state['prior_archive']=old_state['last_known_good_archive']
   next_state['last_known_good_archive']=str(NEW_ARCH)
   next_state['files']=dict(old_state['files'])
   next_state['files'][RENDER.name]=NEW_R
   next_state['files'][PUBLISH.name]=NEW_P
   next_state['watermark_profile']=NEW_ID
   next_state['acceptance']='PASS'
   blob=(json.dumps(next_state,ensure_ascii=False,indent=2)+'\n').encode()
   atomic(STATE,blob,stat.S_IMODE(STATE.stat().st_mode))
   if json.loads(regular(STATE,limit=60000)).get('version')!=NEW_VERSION:
    raise Stop('GUARD_STATE_NOT_PINNED')
   full_acceptance()
   rec={'status':'APPLIED_QA_PASS','release':'RG_NEWS2_WM_AND_GUARD_ATOMIC_REPAIR_20261114',
     'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
     'renderer_sha256':NEW_R,'publisher_sha256':NEW_P,
     'guard_version':NEW_VERSION,'backup_verified':True,
     'old_lkg_preserved':True,'new_lkg_sha256':sha(regular(NEW_ARCH,limit=5000000)),
     'verified_components':len(KEY),'telegram_calls':0,'publications':0}
   atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode(),0o600)
   return rec
  except Exception:
   # Restore all three changes under guard and publishing locks.
   if installed:
    atomic(RENDER,current[RENDER.name],mode_r)
    atomic(PUBLISH,current[PUBLISH.name],mode_p)
    regular(RENDER,OLD_R);regular(PUBLISH,OLD_P)
   atomic(STATE,raw_state,stat.S_IMODE(STATE.stat().st_mode))
   if regular(STATE,limit=60000)!=raw_state:raise Stop('GUARD_ROLLBACK_VERIFICATION_FAILED')
   raise
 finally:
  for fd in reversed(fds):os.close(fd)

def selftest():
 assert len(KEY)==18 and NEW_ID!=OLD_ID
 assert len(NEW_R)==len(NEW_P)==64
 assert len(LOCKS)==4
 assert sha(b'abc')=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
 print('NEWS2_ATOMIC_WM_GUARD_REPAIR_SELFTEST_PASS')

if __name__=='__main__':
 try:
  a=sys.argv[1:]
  if a==['selftest']:selftest()
  elif a==['preflight']:
   _,old,rows,r,p=preflight()
   test_patched_renderers(r,p)
   print(json.dumps({'status':'PREFLIGHT_PASS','old_guard':old['version'],
      'modules_verified':len(rows),'new_renderer_sha256':sha(r),
      'new_publisher_sha256':sha(p),'telegram_calls':0,'publications':0}))
  elif a==['apply']:print(json.dumps(apply(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:160],
      'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
