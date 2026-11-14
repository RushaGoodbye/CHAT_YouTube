#!/usr/bin/env python3
"""NEWS2 Kyiv alert retention V2, pinned atomic installer.

Patch existing strict Kyiv-only original notification cleaner in place:
- delete upon *verified newer channel post*, irrespective of alert age
- retain 12h timeout and 47h Telegram delete time limit
- add media-only post visibility without treating media as alerts
- preserve all non-exact template posts and protect other destinations

No content is deleted during installation, selftests and preview.
Root-only exact pin, immutable backup, atomic replace, rollback on error.
"""
import datetime,fcntl,hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path

BASE=Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=BASE/'operator'
SOURCE=O/'news_rg_alert_24h_cleanup_v1.py'
SHELL=BASE/'rg_news_dsm_tick.sh'
BACKUP_ROOT=O/'rg_news2_release_backups_v6'
RELEASE=BACKUP_ROOT/'kyiv_alert_newpost_or_12h_20261114'
OLD_PY=RELEASE/'news_rg_alert_24h_cleanup_v1.py.before'
OLD_SH=RELEASE/'rg_news_dsm_tick.sh.before'
RECEIPT=RELEASE/'receipt.json'
LOCK=O/'rg_news2_alert_12h_release.lock'
OLD_PY_SHA='73a348ca29b248b2f7f12cb7772d36579ae55e087d24c3435129f94a9c77cbc7'
OLD_SH_SHA='8af9b90331ebee4187f43be62321bef2860354866f80966586afe36453db7dac'
OLD_PARSE="""  content=re.search(r'<div\\\\b[^>]*class=\"[^\\\"]*\\\\btgme_widget_message_text\\\\b[^\\\"]*\"[^>]*>([\\\\s\\\\S]*?)</div>',block)
  if not content:continue
  text=normalize(content.group(1))
  kind=exact_alert_kind(text)
  rows.append({'id':message_id,'timestamp':int(when),'kind':kind,'text_chars':len(text)})"""
NEW_PARSE="""  content=re.search(r'<div\\\\b[^>]*class=\"[^\\\"]*\\\\btgme_widget_message_text\\\\b[^\\\"]*\"[^>]*>([\\\\s\\\\S]*?)</div>',block)
  # Even media-only posts are independent posts and must trigger cleanup of
  # PRECEDING alerts. Without text they can NEVER become cleanup targets.
  text=normalize(content.group(1)) if content else ''
  kind=exact_alert_kind(text) if content else None
  rows.append({'id':message_id,'timestamp':int(when),'kind':kind,'text_chars':len(text)})"""
OLD_SCAN="""def scan(now):
 candidates=[];seen=set();previous_min=None;pages=0
 for num in range(MAX_PAGES):
  posts=page(previous_min)
  if not posts:break
  pages+=1
  ids=[r['id'] for r in posts]
  smallest=min(ids)
  if previous_min is not None and smallest>=previous_min:break
  for row in posts:
   if row['id'] in seen:continue
   seen.add(row['id'])
   age=now-row['timestamp']
   if row['kind'] in ('start','clear') and MIN_AGE<=age<MAX_AGE:
    candidates.append({'id':row['id'],'kind':row['kind'],'age_hours':round(age/3600,2)})
  previous_min=smallest
  if all(now-r['timestamp']>=MAX_AGE for r in posts):break
 return {'pages':pages,'posts_seen':len(seen),'eligible':sorted(candidates,key=lambda x:x['id'])}"""
NEW_SCAN="""def scan(now):
 # Collect publication positions first; a newer post may be located on the
 # previous public HTML page. Message IDs are monotonically increasing.
 # Every deletion target must independently match an EXACT Kyiv template.
 seen={};previous_min=None;pages=0
 for num in range(MAX_PAGES):
  posts=page(previous_min)
  if not posts:break
  pages+=1
  smallest=min(r['id'] for r in posts)
  if previous_min is not None and smallest>=previous_min:break
  for row in posts:
   if row['id'] not in seen:seen[row['id']]=row
  previous_min=smallest
  if all(now-r['timestamp']>=MAX_AGE for r in posts):break
 ordered=sorted(seen.values(),key=lambda r:r['id'])
 eligible=[]
 for row in ordered:
  age=now-row['timestamp']
  if row['kind'] not in ('start','clear') or not 0<=age<MAX_AGE:
   continue
  # Only evidence of a *real, newer* message from THIS public channel,
  # not a repost, pinned quote or neighbouring HTML text, counts.
  newer=next((x for x in reversed(ordered)
              if x['id']>row['id'] and x['timestamp']>=row['timestamp']
              and x['timestamp']<=now),None)
  expired=age>=MIN_AGE
  if not expired and newer is None:continue
  eligible.append({'id':row['id'],'kind':row['kind'],
      'age_hours':round(age/3600,2),
      'trigger':'12h_timeout' if expired else 'newer_channel_post',
      'newer_post_id':newer['id'] if newer else None})
 return {'pages':pages,'posts_seen':len(seen),'eligible':eligible}"""
OLD_SHELL_COMMENT="# NEWS_RG_CHANNEL_ALERT_RETENTION_24H_V1\n# Strict exact-match Kyiv start/clear only, age 24-47h; no news/media cleanup."
NEW_SHELL_COMMENT="# NEWS_RG_CHANNEL_ALERT_RETENTION_V2\n# Strict Kyiv start/clear only: delete after next public post OR 12h (up to Telegram 47h limit)."
class Stop(ValueError):pass
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safety(p,max_bytes=150000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or st.st_size<10 or st.st_size>max_bytes or st.st_uid!=0:
  raise Stop('UNSAFE_ROOT_TARGET_'+p.name)
 return p.read_bytes()
def protected_dir(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_BACKUP_PARENT_'+p.name)
def replace_exact(text,old,new,anchor):
 if text.count(old)!=1:raise Stop('CODE_ANCHOR_DRIFT_'+anchor)
 return text.replace(old,new,1)
def patched(a,b):
 py=a.decode('utf8')
 sh=b.decode('utf8')
 py=replace_exact(py,OLD_PARSE,NEW_PARSE,'parse_media_only')
 py=replace_exact(py,OLD_SCAN,NEW_SCAN,'newer_post_retention')
 py=replace_exact(py,
  'Only verified exact-format cards between 12 and 47 hours old; no posts or approvals.',
  'Only exact Kyiv start/clear; newer-post OR 12h timeout; never other posts.',
  'docstring')
 sh=replace_exact(sh,OLD_SHELL_COMMENT,NEW_SHELL_COMMENT,'DSM_comment')
 compile(py,'news_rg_alert_24h_cleanup_v1.py','exec')
 if sh.count("news_rg_alert_24h_cleanup_v1.py' tick")!=1:raise Stop('DUPLICATE_TICK')
 if sha(a)==sha(py.encode()) or sha(b)==sha(sh.encode()):raise Stop('UNCHANGED_PATCH')
 return py.encode('utf8'),sh.encode('utf8')
def preflight():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 protected_dir(O)
 if any(p.is_symlink() for p in (BACKUP_ROOT,RELEASE,OLD_PY,OLD_SH,RECEIPT,LOCK)):
  raise Stop('RELEASE_SYMLINK')
 if RELEASE.exists():raise Stop('RELEASE_ALREADY_USED')
 a=safety(SOURCE);b=safety(SHELL)
 if sha(a)!=OLD_PY_SHA or sha(b)!=OLD_SH_SHA:
  raise Stop('PINNED_RELEASE_SOURCE_DRIFT')
 newer=patched(a,b)
 return a,b,*newer
def verify_tests(py):
 with tempfile.TemporaryDirectory(prefix='rg_alert_v2_offline_') as td:
  temp=Path(td)/'news_rg_alert_24h_cleanup_v1.py'
  temp.write_bytes(py)
  out=subprocess.run(['/usr/bin/python3',str(temp),'selftest'],
         capture_output=True,text=True,timeout=20)
  if out.returncode or 'NEWS_RG_ALERT_24H_CLEANUP_SELFTEST_PASS' not in out.stdout:
   raise Stop('RELEASE_SELFTEST_FAILED')
 return True
def atomic(p,b,mode):
 fd,t=tempfile.mkstemp(prefix='.rg_alert_v2_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  if os.path.exists(t):os.unlink(t)
def install():
 lock_fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  a,b,c,d=preflight()
  verify_tests(c)
  protected_dir(BACKUP_ROOT,create=True);protected_dir(RELEASE,create=True)
  ma=stat.S_IMODE(SOURCE.stat().st_mode);mb=stat.S_IMODE(SHELL.stat().st_mode)
  atomic(OLD_PY,a,0o600);atomic(OLD_SH,b,0o600)
  if sha(safety(OLD_PY))!=OLD_PY_SHA or sha(safety(OLD_SH))!=OLD_SH_SHA:
   raise Stop('BACKUP_VERIFICATION_FAILED')
  attempted=False
  try:
   atomic(SOURCE,c,ma);attempted=True
   atomic(SHELL,d,mb)
   if sha(safety(SOURCE))!=sha(c) or sha(safety(SHELL))!=sha(d):
    raise Stop('POSTINSTALL_SHA_MISMATCH')
   verify_tests(c)
   shcheck=subprocess.run(['/bin/sh','-n',str(SHELL)],capture_output=True,timeout=15)
   if shcheck.returncode:raise Stop('DSM_SHELL_SYNTAX_FAILED')
   rec={'status':'APPLIED_QA_PASS','release':'NEWS2_KYIV_ALERT_NEWPOST_OR_12H_20261114',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'old_python_sha256':OLD_PY_SHA,'new_python_sha256':sha(c),
        'old_dsm_sha256':OLD_SH_SHA,'new_dsm_sha256':sha(d),
        'backup_verified':True,'schedule':'existing DSM tick 10m cooldown',
        'policy':'newer public channel post OR 12 hours','telegram_calls':0,
        'publications':0,'deletions_during_install':0}
   atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode('utf8'),0o600)
   return rec
  except Exception:
   if attempted:
    atomic(SOURCE,a,ma);atomic(SHELL,b,mb)
    if sha(safety(SOURCE))!=OLD_PY_SHA or sha(safety(SHELL))!=OLD_SH_SHA:
     raise Stop('ROLLBACK_VERIFICATION_FAILED')
   raise
 finally:os.close(lock_fd)
def selftest():
 assert len(OLD_PY_SHA)==len(OLD_SH_SHA)==64
 assert 'newer_channel_post' in NEW_SCAN
 assert 'MIN_AGE' in NEW_SCAN and 'MAX_AGE' in NEW_SCAN
 assert NEW_SHELL_COMMENT.count('12h')==1
 print('NEWS2_ALERT_NEWPOST_OR_12H_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['preflight']:
   a,b,c,d=preflight()
   verify_tests(c)
   print(json.dumps({'status':'PREFLIGHT_PASS',
     'new_python_sha256':sha(c),'new_dsm_sha256':sha(d),
     'publication_count':0,'delete_count':0},sort_keys=True))
  elif mode==['apply']:print(json.dumps(install(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
    'publication_count':0,'deletion_count':0}))
  raise SystemExit(2)
