#!/usr/bin/env python3
"""NEWS2 SINGLE-OWNER YouTube Tue/Thu 18:00 Kyiv schedule release.

Fixed deployment to existing RG NEWS2 DSM tick. No new pollers, no bot token
changes, no cron installs or Worker deploys. Does not send on apply.
Guards owner exclusivity, SHA-pinned source, Kyiv clock, acceptance, lock,
backup/atomic replace/post-QA/automatic rollback.

Reuses existing production news_rg_youtube_top_schedule_v1.py, which sends a
YouTube watch link + HTML caption and required clickable project footer.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

BASE=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=BASE/'operator'
TICK=BASE/'rg_news_dsm_tick.sh'
YOUTUBE=O/'news_rg_youtube_top_schedule_v1.py'
CF_SOURCE=Path('/volume1/docker/RG_CONTENT_DEPLOY/cloudflare-content-hub/src/index.js')
CF_CONFIG=Path('/volume1/docker/RG_CONTENT_DEPLOY/cloudflare-content-hub/src/config.js')
OWNER=O/'rg_news2_youtube_owner_nas_v1.json'
BACKUPS=O/'rg_news2_release_backups_v4'
RELEASE=BACKUPS/'youtube_nas_owner_20261114'
PREV=RELEASE/'rg_news_dsm_tick_before.sh'
RECEIPT=RELEASE/'receipt.json'
LOCK=O/'rg_news2_youtube_owner_release.lock'
APPROVED_TICK_SHA='bf45f8dbcdee9577d92eb5aa3c465361a2d6da74868733fdfeab702b2aa1ce2d'
APPROVED_YT_SHA='83842e3fe7da60d7758070e0aec0b950f30cc0358b85ea0e056ab271ebd0fe2a'
APPROVED_CF_SOURCE_SHA='39474c68ed2fbba08a6ca40621b7c53422271613c6f321828f3c7eba6b7aae70'
APPROVED_CF_CONFIG_SHA='d12ba57657c97385a683b5fe7393b0c22eb4a53d2b5a4796fef526f36c0f91e3'
OLD_BLOCK=(
 '# NEWS_RG_YOUTUBE_TOP_SINGLE_OWNER_V1\n'
 '# NAS duplicate disabled: Cloudflare owns Tue/Thu 18:00 Europe/Kyiv.\n'
 '# The existing NAS script remains installed for a controlled owner change.\n'
)
NEW_BLOCK=(
 '# NEWS_RG_YOUTUBE_TOP_SINGLE_OWNER_V2_NAS\n'
 '# Verified NAS-only owner: Cloudflare contains passive YouTube relay but no top selector.\n'
 '# One existing DSM schedule only. Tue/Thu 18:00 Europe/Kyiv, durable no-repeat state.\n'
 '"$RG_NEWS_PYTHON" \'/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_youtube_top_schedule_v1.py\' tick >> \'/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_stability_releases_v1/youtube_schedule.log\' 2>&1 || :\n'
)
class Stop(ValueError):pass

def sha(b):return hashlib.sha256(b).hexdigest()
def regular(p,expected=None,maxlen=200000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size<1 or st.st_size>maxlen:
  raise Stop('UNSAFE_FILE_'+p.name)
 if p==YOUTUBE:
  # Existing NAS script is a SHA256-pinned READ-ONLY input inside the
  # separate root-owned mode-0700 operator directory, verified above.
  # DSM ACL may present 0666 even for files not accessible to users.
  # Do not change ACL or use this exception for any release target.
  parent=O.lstat()
  if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=0
      or parent.st_mode&0o077 or st.st_uid!=0 or not expected):
   raise Stop('YOUTUBE_SOURCE_PROTECTED_PARENT_OR_PIN_UNSAFE')
 elif p in (CF_SOURCE,CF_CONFIG):
  # Root-owned SHA-pinned read-only references. Synology uses 0664.
  if st.st_uid!=0 or st.st_mode&0o002 or not expected:
   raise Stop('CF_REFERENCE_PERMISSIONS_OR_PIN_UNSAFE')
 elif st.st_mode&0o022:
  raise Stop('UNSAFE_FILE_'+p.name)
 b=p.read_bytes()
 if expected and sha(b)!=expected:raise Stop('SOURCE_SHA_CHANGED_'+p.name)
 return b
def root_dir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode):
  raise Stop('UNSAFE_DIR_'+p.name)
 if p==BASE:
  # DSM shared-folder ACL root: base is owned by its NAS user and
  # displayed 0777+; do not change its ACL or claim it is root-owned.
  # The actual release target is independently SHA pinned, root-owned 0700.
  target=TICK.lstat()
  if not stat.S_ISREG(target.st_mode) or target.st_uid!=0 or target.st_mode&0o077:
   raise Stop('DSM_ROOT_OWNED_TICK_TARGET_UNSAFE')
  return
 if st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_DIR_'+p.name)

def program_assertions():
 root_dir(O);root_dir(BASE)
 b=regular(TICK,APPROVED_TICK_SHA)
 y=regular(YOUTUBE,APPROVED_YT_SHA)
 cf=regular(CF_SOURCE,APPROVED_CF_SOURCE_SHA,150000)
 config=regular(CF_CONFIG,APPROVED_CF_CONFIG_SHA,maxlen=25000).decode()
 st=b.decode('utf8')
 if st.count(OLD_BLOCK)!=1 or 'news_rg_youtube_top_schedule_v1.py\' tick' in st:
  raise Stop('DSM_SCHEDULE_CONTRACT_CHANGED')
 if st.count('news_rg_publication_schedule_v1.py')!=1 or st.count('news_rg_nas_video_schedule_v1.py')!=1:
  raise Stop('EXISTING_DSM_HOOKS_CHANGED')
 if 'RG_NEWS_PYTHON' not in st or 'python-3.15.2' not in st:
  raise Stop('DSM_PINNED_PYTHON_NOT_FOUND')
 if 'async scheduled(' not in cf.decode() or '/internal/youtube-post' not in cf.decode():
  raise Stop('CLOUDFLARE_RELAY_CONTRACT_CHANGED')
 if 'youtube' in config.lower() and any(x in config.lower() for x in ('tuesday','thursday','youtube_top')):
  raise Stop('CLOUDFLARE_YOUTUBE_SCHEDULE_NEEDS_REVIEW')
 if not all(x in y.decode() for x in ("SOURCE='https://www.youtube.com/@RussiaGoodbye/videos'",
        "now.weekday() in (1,3)","now.hour==18",'SEND_UNCERTAIN_NO_RETRY','random.SystemRandom().choice(fresh)',
        "'sendMessage'",'FOOTER','verify_channel')):
  raise Stop('YOUTUBE_SOURCE_SAFETY_CONTRACT_CHANGED')
 # A release that only changes the schedule, never the YouTube source.
 new=st.replace(OLD_BLOCK,NEW_BLOCK,1).encode()
 if new.count(b'news_rg_youtube_top_schedule_v1.py')!=1:
  raise Stop('YOUTUBE_DOUBLE_SCHEDULE')
 # Enforce no extra cron, getUpdates or unsafe poller.
 if 'getUpdates' in NEW_BLOCK:raise Stop('SECOND_POLLER')
 return b,new

def shell_qa(content):
 with tempfile.TemporaryDirectory(prefix='rg_news2_yt_shell_') as td:
  file=Path(td)/'tick.sh';file.write_bytes(content)
  result=subprocess.run(['/bin/sh','-n',str(file)],capture_output=True,text=True,timeout=12)
  if result.returncode:raise Stop('DSM_SHELL_SYNTAX_FAILED')
 return True

def module_qa():
 py=O/'tools/python-3.15.2/bin/python3.15'
 if not py.is_file() or py.is_symlink():raise Stop('PYTHON315_MISSING')
 test=subprocess.run([str(py),str(YOUTUBE),'selftest'],capture_output=True,text=True,timeout=20)
 if test.returncode or 'NEWS_RG_TOP_YOUTUBE_SCHEDULE_SELFTEST_PASS' not in test.stdout:
  raise Stop('YOUTUBE_SELFTEST_FAIL')
 return True

def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 if any(p.is_symlink() for p in (LOCK,BACKUPS,RELEASE,PREV,RECEIPT,OWNER)):
  raise Stop('UNSAFE_SYMLINK')
 if OWNER.exists() or RECEIPT.exists():raise Stop('RELEASE_ALREADY_EXISTS')
 before,after=program_assertions()
 shell_qa(after)
 module_qa()
 return before,after

def atomic(p,bytes_,mode):
 fd,temp=tempfile.mkstemp(prefix='.rg_news2_yt_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(bytes_);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
 finally:
  if os.path.exists(temp):os.unlink(temp)

def locked():
 if LOCK.is_symlink():raise Stop('LOCK_SYMLINK')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 return fd

def apply():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 fd=locked()
 try:
  before,after=preflight()
  root_dir(BACKUPS,create=True);root_dir(RELEASE,create=True)
  if PREV.exists() or RECEIPT.exists() or OWNER.exists():raise Stop('RELEASE_OR_OWNER_ALREADY_EXISTS')
  atomic(PREV,before,0o600)
  if regular(PREV,APPROVED_TICK_SHA)!=before:raise Stop('BACKUP_NOT_VERIFIED')
  mode=stat.S_IMODE(TICK.stat().st_mode)
  try:
   atomic(TICK,after,mode)
   if regular(TICK,sha(after))!=after:raise Stop('SHELL_POSTINSTALL_DRIFT')
   shell_qa(regular(TICK));module_qa()
   owner={'schema':'RG_NEWS2_YOUTUBE_OWNER_V1','owner':'nas',
       'approved_at':'2026-11-14','schedule':'Tue/Thu 18:00 Europe/Kyiv',
       'module_sha256':APPROVED_YT_SHA,'source':'https://www.youtube.com/@RussiaGoodbye/videos',
       'no_second_poller':True,'cloudflare_youtube_relay':'passive_no_top_selector',
       'publications_during_install':0}
   atomic(OWNER,(json.dumps(owner,sort_keys=True)+'\n').encode(),0o600)
   receipt={'release':'RG_NEWS2_YOUTUBE_NAS_SINGLE_OWNER_20261114',
       'status':'APPLIED_QA_PASS','before_sha':APPROVED_TICK_SHA,
       'after_sha':sha(after),'backup_verified':True,
       'module_selftest':'PASS','schedule_sh_n':'PASS',
       'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'telegram_calls':0,'publications':0,'worker_changes':0}
   atomic(RECEIPT,(json.dumps(receipt,sort_keys=True)+'\n').encode(),0o600)
   return receipt
  except Exception:
   atomic(TICK,before,mode)
   regular(TICK,APPROVED_TICK_SHA)
   if OWNER.is_file() and not OWNER.is_symlink():OWNER.unlink()
   raise
 finally:os.close(fd)

def rollback():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 root_dir(BACKUPS);root_dir(RELEASE)
 old=regular(PREV,APPROVED_TICK_SHA)
 rec=json.loads(regular(RECEIPT))
 if rec.get('status')!='APPLIED_QA_PASS':raise Stop('BAD_RECEIPT')
 new=old.decode().replace(OLD_BLOCK,NEW_BLOCK,1).encode()
 fd=locked()
 try:
  regular(TICK,sha(new))
  atomic(TICK,old,stat.S_IMODE(TICK.stat().st_mode))
  regular(TICK,APPROVED_TICK_SHA)
  if OWNER.exists():OWNER.unlink()
  return {'status':'ROLLBACK_VERIFIED','publications':0}
 finally:os.close(fd)

def selftest():
 assert OLD_BLOCK.count('Cloudflare owns')==1
 assert NEW_BLOCK.count('news_rg_youtube_top_schedule_v1.py')==1
 assert 'getUpdates' not in NEW_BLOCK
 assert len(APPROVED_YT_SHA)==len(APPROVED_TICK_SHA)==64
 print('NEWS2_YOUTUBE_NAS_OWNER_INSTALLER_SELFTEST_PASS')

if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['preflight']:
   old,new=preflight()
   print(json.dumps({'status':'PREFLIGHT_PASS','before_sha':sha(old),
     'after_sha':sha(new),'module_selftest':'PASS','publications':0}))
  elif mode==['apply']:print(json.dumps(apply(),sort_keys=True))
  elif mode==['rollback']:print(json.dumps(rollback(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:125],
    'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
