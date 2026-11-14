#!/usr/bin/env python3
"""NEWS2 user-approved watermark placement release (2026-11-14).

ONE pinned change to the root-owned installed NAS:
 * preserve EXACT approved 2026-11-04 RG / RUSSIA GOODBYE PNG sha256
 * move overlay to upper-right, width 40%, alpha 78%, edge margins 3%
 * change PSNR verification ROI from center to upper-right
 * change publisher receipt profile pin; old center renders fail closed
 * add a new approved top-right profile (old Nov4 profile is retained)

Backups, locks, atomic writes, pre/post QA, automatic rollback.
No bot API calls, video downloads, Telegram publication, runner changes,
new pollers, arbitrary command execution or user-supplied paths.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
RENDER=ROOT/'news_rg_nas_video_pipeline_v1.py'
PUBLISH=ROOT/'news_rg_approved_video_publication_v1.py'
IMAGE=ROOT/'assets/rg_approved_watermark_20261104.png'
NOV4=ROOT/'assets/approved_watermark_profile_20261104.json'
NEW_PROFILE_FILE=ROOT/'assets/approved_watermark_profile_20261114.json'
FFMPEG=ROOT/'tools/ffmpeg/bin/ffmpeg'
RELEASE_BASE=ROOT/'rg_news2_release_backups_v3'
RELEASE=RELEASE_BASE/'wm_topright_20261114'
BACKUP_RENDER=RELEASE/'video_renderer_before.py'
BACKUP_PUBLISH=RELEASE/'video_publisher_before.py'
RECEIPT=RELEASE/'release_receipt.json'
LOCKS=[
 ROOT/'news_rg_nas_video_schedule.lock',
 ROOT/'news_rg_nas_video_pipeline.lock',
 ROOT/'news_rg_publication.lock'
]
PIN={
 'render':'59b87da6057482702807837948da46307396fc4e63e2a2fc7c181ec692c10e55',
 'publish':'7a3fdfdd443803834c0da18a05d3a5cde512ed34322e64bce89255d68a6dd395',
 'image':'1e852e8540d079ebf275294a784559557098dab455f14bcfa1efe86152b73585',
 'nov4':'1779d32f9026a11009793c903743974ed349a830408941f74e532601ee1790a5',
}
OLD_ID='RG_APPROVED_20261104_CENTER_040_078'
NEW_ID='RG_APPROVED_20261114_TOPRIGHT_040_078'
OLD_OVERLAY='overlay=(W-w)/2:(H-h)/2:shortest=0:eof_action=repeat:repeatlast=1[v]'
NEW_OVERLAY='overlay=W-w-W*0.03:H*0.03:shortest=0:eof_action=repeat:repeatlast=1[v]'
OLD_ROI='crop=iw*0.38:ih*0.20:(iw-iw*0.38)/2:(ih-ih*0.20)/2'
NEW_ROI='crop=iw*0.44:ih*0.24:iw-iw*0.44:0'
class Stop(Exception):pass

def digest(data):return hashlib.sha256(data).hexdigest()

def safe_read(p,expected=None,limit=600000):
 s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or not 1<=s.st_size<=limit:
  raise Stop('FILE_NOT_REGULAR_'+p.name)
 if s.st_mode & 0o022:raise Stop('FILE_PERMISSIONS_UNSAFE_'+p.name)
 b=p.read_bytes()
 if expected and digest(b)!=expected:raise Stop('FILE_HASH_DRIFT_'+p.name)
 return b

def checked_dir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:
  raise Stop('DIRECTORY_UNSAFE_'+p.name)

def replace_one(src,a,b,count):
 if src.count(a)!=count:raise Stop('SOURCE_CONTRACT_DRIFT_'+a[:30])
 return src.replace(a,b)

def patches(render,publish):
 r=render.decode('utf8')
 v=publish.decode('utf8')
 r=replace_one(r,OLD_ID,NEW_ID,2)
 r=replace_one(r,OLD_OVERLAY,NEW_OVERLAY,1)
 r=replace_one(r,OLD_ROI,NEW_ROI,2)
 v=replace_one(v,OLD_ID,NEW_ID,1)
 if OLD_ID in r or OLD_ID in v or OLD_OVERLAY in r or OLD_ROI in r:
  raise Stop('OLD_WM_PROFILE_REMAINS')
 if PIN['image'] not in r or PIN['image'] not in v:
  raise Stop('BRANDING_HASH_PIN_LOST')
 if 'PUBLIC_SEND_UNCERTAIN_NO_RETRY' not in v or 'caption_entities' not in v:
  raise Stop('VIDEO_PUBLISH_SAFETY_GATE_LOST')
 if 'audio_integrity' not in r or 'motion_qa' not in r or 'watermark_visibility_qa' not in r:
  raise Stop('RENDER_SAFETY_GATE_LOST')
 for name,src in [('render',r),('publish',v)]:
  compile(src,name+'_patched.py','exec')
 return r.encode('utf8'),v.encode('utf8')

def new_profile():
 return {
   'schema':'RG_APPROVED_VIDEO_WATERMARK_V2',
   'approved_at':'2026-11-14',
   'approval_source':'user_provided_visual_reference_20261114',
   'supersedes_profile':OLD_ID,
   'logo':'rg_approved_watermark_20261104.png',
   'sha256':PIN['image'],
   'intrinsic_resolution':[600,343],
   'position':'top_right',
   'margin_top':0.03,'margin_right':0.03,
   'scale_width':0.4,'alpha':0.78,
   'legacy_asset_disabled':True,
   'watermark_profile':NEW_ID,
   'placement_formula':'overlay=W-w-W*0.03:H*0.03',
   'verified_at':'2026-11-14',
   'image_asset_preserved':True,
 }

def profile_bytes():
 return (json.dumps(new_profile(),ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf8')

def original_contract():
 checked_dir(ROOT);checked_dir(ROOT/'assets')
 old_r=safe_read(RENDER,PIN['render'])
 old_v=safe_read(PUBLISH,PIN['publish'])
 safe_read(IMAGE,PIN['image'],15000000)
 old_profile=json.loads(safe_read(NOV4,PIN['nov4']))
 if old_profile.get('watermark_profile')!=OLD_ID or old_profile.get('sha256')!=PIN['image']:
  raise Stop('NOV4_PINNED_APPROVAL_CHANGED')
 return old_r,old_v

def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 for p in [*LOCKS,RELEASE_BASE,RELEASE,BACKUP_RENDER,BACKUP_PUBLISH,RECEIPT,NEW_PROFILE_FILE]:
  if p.is_symlink():raise Stop('SYMLINK_'+p.name)
 if NEW_PROFILE_FILE.exists() or RECEIPT.exists():raise Stop('RELEASE_ALREADY_EXISTS')
 old_r,old_v=original_contract()
 new_r,new_v=patches(old_r,old_v)
 return (old_r,old_v,new_r,new_v)

def run_py_smoketest(body,filename):
 with tempfile.TemporaryDirectory(prefix='news2_wm_source_') as td:
  p=Path(td)/filename;p.write_bytes(body)
  proc=subprocess.run(['/usr/bin/python3',str(p),'selftest'],
             capture_output=True,text=True,timeout=15)
  if proc.returncode!=0 or '_SELFTEST_PASS' not in proc.stdout:
   raise Stop('SELFTEST_FAILED_'+filename)

def video_test():
 if FFMPEG.is_symlink() or not FFMPEG.is_file():
  raise Stop('FFMPEG_NOT_AVAILABLE')
 # Actual 360x640, 2-second synthetic video on the NAS, not Telegram.
 with tempfile.TemporaryDirectory(prefix='news2_wm_video_') as td:
  td=Path(td);src=td/'src.mp4';out=td/'wm.mp4'
  input_cmd=[str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y',
    '-f','lavfi','-i','testsrc2=size=360x640:rate=24:duration=2',
    '-c:v','libx264','-pix_fmt','yuv420p',str(src)]
  result=subprocess.run(input_cmd,capture_output=True,timeout=40)
  if result.returncode or not src.is_file():raise Stop('VIDEO_TEST_SOURCE_FAILED')
  filtergraph='[1:v][0:v]scale2ref=w=main_w*0.40:h=ow/mdar[wm][base];[wm]format=rgba,colorchannelmixer=aa=0.78[logo];[base][logo]'+NEW_OVERLAY
  cmd=[str(FFMPEG),'-nostdin','-hide_banner','-loglevel','error','-y',
    '-i',str(src),'-i',str(IMAGE),'-filter_complex',filtergraph,
    '-map','[v]','-c:v','libx264','-crf','21','-preset','fast',str(out)]
  result=subprocess.run(cmd,capture_output=True,timeout=90)
  if result.returncode or not out.is_file() or out.stat().st_size<1500:
   raise Stop('VIDEO_TEST_RENDER_FAILED')
  # PSNR in the actual new logo region, same ROI as production.
  graph=('[0:v]'+NEW_ROI+',format=yuv420p[a];'
         '[1:v]'+NEW_ROI+',format=yuv420p[b];'
         '[a][b]psnr=stats_file=-[diff]')
  check=subprocess.run([str(FFMPEG),'-nostdin','-hide_banner','-i',str(src),'-i',str(out),
      '-filter_complex',graph,'-map','[diff]','-frames:v','36','-f','null','-'],
      capture_output=True,text=True,timeout=40)
  if check.returncode:raise Stop('VIDEO_TEST_WM_VISIBILITY_FAILED')
  import re
  psnrs=[float(x) for x in re.findall(r'psnr_avg:([0-9.]+)',check.stdout+check.stderr)]
  if len(psnrs)<30 or sum(psnrs)/len(psnrs)>=25:
   raise Stop('VIDEO_TEST_TOPRIGHT_PRESENCE_MISSING')
  return {'status':'NAS_TEST_VIDEO_RENDER_PASS','frames_checked':len(psnrs),
          'topright_psnr':round(sum(psnrs)/len(psnrs),2)}

def qa_on_bytes(new_r,new_v,video=True):
 run_py_smoketest(new_r,'news_rg_nas_video_pipeline_v1.py')
 run_py_smoketest(new_v,'news_rg_approved_video_publication_v1.py')
 if video:return video_test()
 return {'status':'SELFTEST_PASS'}

def atomic_write(target,raw,mode):
 fd,tmp=tempfile.mkstemp(prefix='.news2_wm_release_',dir=str(target.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
  os.replace(tmp,target)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def acquire():
 openfds=[]
 try:
  for path in LOCKS:
   fd=os.open(str(path),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except Exception:os.close(fd);raise
   openfds.append(fd)
  return openfds
 except Exception:
  for fd in reversed(openfds):os.close(fd)
  raise Stop('RENDER_OR_PUBLISH_BUSY')

def install():
 before_r,before_v,new_r,new_v=preflight()
 # Tests before acquiring any production locks.
 qa_on_bytes(new_r,new_v,video=True)
 fds=acquire()
 try:
  original_contract() # recheck hashes after locks
  checked_dir(RELEASE_BASE,create=True);checked_dir(RELEASE,create=True)
  if BACKUP_RENDER.exists() or BACKUP_PUBLISH.exists() or RECEIPT.exists() or NEW_PROFILE_FILE.exists():
   raise Stop('BACKUP_OR_RELEASE_ALREADY_EXISTS')
  atomic_write(BACKUP_RENDER,before_r,0o600)
  atomic_write(BACKUP_PUBLISH,before_v,0o600)
  safe_read(BACKUP_RENDER,PIN['render'])
  safe_read(BACKUP_PUBLISH,PIN['publish'])
  installed=False
  oldmode_r=stat.S_IMODE(RENDER.stat().st_mode)
  oldmode_v=stat.S_IMODE(PUBLISH.stat().st_mode)
  try:
   atomic_write(RENDER,new_r,oldmode_r)
   installed=True
   atomic_write(PUBLISH,new_v,oldmode_v)
   atomic_write(NEW_PROFILE_FILE,profile_bytes(),0o600)
   safe_read(RENDER,digest(new_r));safe_read(PUBLISH,digest(new_v))
   if json.loads(safe_read(NEW_PROFILE_FILE))!=new_profile():
    raise Stop('PROFILE_POSTINSTALL_MISMATCH')
   qa=qa_on_bytes(safe_read(RENDER),safe_read(PUBLISH),video=False)
   receipt={'status':'APPLIED_QA_PASS',
     'release':'RG_NEWS2_WATERMARK_TOPRIGHT_20261114',
     'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
     'before':{'render':PIN['render'],'publish':PIN['publish']},
     'after':{'render':digest(new_r),'publish':digest(new_v)},
     'approved_logo_sha256':PIN['image'],'watermark_profile':NEW_ID,
     'backup_verified':True,'test_video_qa':'PASS',
     'postinstall_qa':qa,'telegram_calls':0,'publications':0,
     'no_second_poller':True,'old_center_render_receipts_fail_closed':True}
   atomic_write(RECEIPT,(json.dumps(receipt,sort_keys=True)+'\n').encode(),0o600)
   return receipt
  except Exception:
   if installed:
    atomic_write(RENDER,before_r,oldmode_r)
    atomic_write(PUBLISH,before_v,oldmode_v)
    safe_read(RENDER,PIN['render']);safe_read(PUBLISH,PIN['publish'])
   if NEW_PROFILE_FILE.exists() and not NEW_PROFILE_FILE.is_symlink():
    NEW_PROFILE_FILE.unlink()
   raise
 finally:
  for fd in reversed(fds):os.close(fd)

def rollback():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 checked_dir(RELEASE_BASE);checked_dir(RELEASE)
 old_r=safe_read(BACKUP_RENDER,PIN['render'])
 old_v=safe_read(BACKUP_PUBLISH,PIN['publish'])
 rec=json.loads(safe_read(RECEIPT))
 if rec.get('status')!='APPLIED_QA_PASS' or rec.get('watermark_profile')!=NEW_ID:
  raise Stop('RECEIPT_INVALID')
 new_r,new_v=patches(old_r,old_v)
 fds=acquire()
 try:
  safe_read(RENDER,digest(new_r));safe_read(PUBLISH,digest(new_v))
  safe_read(NEW_PROFILE_FILE,digest(profile_bytes()))
  atomic_write(RENDER,old_r,stat.S_IMODE(RENDER.stat().st_mode))
  atomic_write(PUBLISH,old_v,stat.S_IMODE(PUBLISH.stat().st_mode))
  safe_read(RENDER,PIN['render']);safe_read(PUBLISH,PIN['publish'])
  NEW_PROFILE_FILE.unlink()
  return {'status':'ROLLBACK_VERIFIED','telegram_calls':0,'publications':0}
 finally:
  for fd in reversed(fds):os.close(fd)

def selftest():
 assert len(PIN['render'])==64 and len(PIN['publish'])==64
 assert 'TOPRIGHT' in NEW_ID and NEW_OVERLAY.count('0.03')==2
 assert NEW_ROI.count('0.44')==2
 assert new_profile()['sha256']==PIN['image']
 print('NEWS2_TOPRIGHT_PINNED_INSTALLER_SELFTEST_PASS')

if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['preflight']:
   old_r,old_v,new_r,new_v=preflight()
   qa=qa_on_bytes(new_r,new_v,video=True)
   print(json.dumps({'status':'PREFLIGHT_PASS','test_video':qa,
      'logo_sha256':PIN['image'],'new_profile':NEW_ID,'publications':0},sort_keys=True))
  elif mode==['apply']:print(json.dumps(install(),sort_keys=True))
  elif mode==['rollback']:print(json.dumps(rollback(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120],
      'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
