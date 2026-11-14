#!/usr/bin/env python3
"""NEWS2 atomic upgrade for health alerts, known pinned stable5.2 and rate-limit.

Changes exactly 3 existing stable-pinned modules + the full 18-component LKG
metadata and archive. Root-only, one guarded release lock, source SHA256 pinned,
no Telegram API, no polling, publishing or autonomous-health invocation.
Uncertain private sends remain quarantined and NEVER auto-retried or deleted.
"""
import datetime,fcntl,hashlib,io,json,os,stat,subprocess,sys,tarfile,tempfile,time
from pathlib import Path

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
PIN=R/'pinned_release_v1.json'
LOCK=R/'release.lock'
RELEASE=R/'health_monitor_20261114'
BEFORE=RELEASE/'pinned_release_before.json'
ARCHIVE=RELEASE/'last_known_good_health_monitor.tar.gz'
RECEIPT=RELEASE/'receipt.json'
OLD_VERSION='2026-11-14-stable5.2-topright-watermark'
NEW_VERSION='2026-11-14-stable5.3-health-monitor'
OLD={
 'news_rg_stability_healthcheck_v1.py':'efde02935ce5b56cdcc8dc607a9bf2803bb17d714c4072a6358d3ef9b92f87fd',
 'news_rg_stable5_operational_gate_v1.py':'9a58661a92f135375a205d8bca58fc9dbc99ccba36796039fdf39d9225b8511b',
 'news_rg_autonomous_health_v1.py':'341cfb4a06d6a6d90f073e8e4fe6e44c8d97b124075d32c3a91ed67f770821bd'
}
KEY=('news_rg_manual_link_intake_v1.py','news_rg_editorial_callbacks_v1.py',
 'news_rg_approved_text_publication_v1.py','news_rg_durable_private_sender_v1.py',
 'news_rg_durable_private_dispatch_v1.py','news_rg_stability_healthcheck_v1.py',
 'news_rg_continuous_callback_v1.py','news_rg_publication_schedule_v1.py',
 'news_rg_editorial_rank_v1.py','news_rg_nas_video_pipeline_v1.py',
 'news_rg_stable5_operational_gate_v1.py','news_rg_autonomous_health_v1.py',
 'news_rg_release_acceptance_v1.py','news_rg_source_shadow_ingest_v1.py',
 'news_rg_approved_video_publication_v1.py','news_rg_video_watermark_handoff_v1.py',
 'news_rg_nas_video_schedule_v1.py','news_rg_editorial_ai_gate_v1.py')
HEALTH='news_rg_stability_healthcheck_v1.py'
GATE='news_rg_stable5_operational_gate_v1.py'
NOTICE='news_rg_autonomous_health_v1.py'
PY=O/'tools/python-3.15.2/bin/python3.15'
class Stop(ValueError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def safe(p,limit=1500000):
 st=p.lstat()
 if not stat.S_ISREG(st.st_mode) or not 1<=st.st_size<=limit or st.st_uid!=0:
  raise Stop('UNSAFE_SOURCE_'+p.name)
 return p.read_bytes()
def directory(p,create=False):
 if create and not p.exists():p.mkdir(mode=0o700)
 st=p.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
  raise Stop('UNSAFE_DIRECTORY_'+p.name)
def atomic(p,b,mode=0o600):
 fd,tmp=tempfile.mkstemp(prefix='.rg_health_pin_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def rep(src,old,new,tag):
 if src.count(old)!=1:raise Stop('PATCH_ANCHOR_CHANGED_'+tag)
 return src.replace(old,new,1)
def patches(items):
 h=items[HEALTH].decode('utf8')
 # Existing old uncertain PRIVATE sends stay safely quarantined, and are
 # reported as warning for manual reconciliation after first 2h, not "critical
 # infrastructure down". Missing timestamps are fail-closed critical.
 h=rep(h,
  " waiting=[];confirmed=0;withdrawn=0;newest=None;keys=set()",
  " waiting=[];confirmed=0;withdrawn=0;newest=None;keys=set()\n uncertain_recent=0;uncertain_old=0;rejected_no_retry=0",
  'private_counts')
 h=rep(h,
  """  if v.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
   flag(alerts,'CRITICAL','PRIVATE_SEND_UNCERTAIN','Возможная отправка; повтор запрещён')""",
  """  if v.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
   # Preserving no-retry is mandatory; this only changes alert severity.
   stamp=v.get('created_at') or v.get('claimed_at') or p.stat().st_mtime
   minutes=age_minutes(stamp,now)
   if minutes is None or minutes<120:
    uncertain_recent+=1
    flag(alerts,'CRITICAL','PRIVATE_SEND_UNCERTAIN_RECENT',
         'Неопределённая приватная отправка менее 2 часов назад; повтор запрещён')
   else:
    uncertain_old+=1
    flag(alerts,'WARNING','PRIVATE_SEND_RECONCILIATION_PENDING',
         'Старая неопределённая отправка требует сверки; автоповтор запрещён')
  elif v.get('status')=='HTTP_REJECTED_NO_RETRY':
   rejected_no_retry+=1""",
  'uncertain_age_classification')
 h=rep(h,
  " return {'status':'OK','confirmed_private_cards':confirmed,\n    'waiting_for_human_count':len(waiting),'system_withdrawn_count':withdrawn,'pending_cards':waiting[:3],",
  " return {'status':'OK','confirmed_private_cards':confirmed,\n    'uncertain_recent_critical':uncertain_recent,'uncertain_old_reconcile':uncertain_old,\n    'http_rejected_no_retry':rejected_no_retry,\n    'waiting_for_human_count':len(waiting),'system_withdrawn_count':withdrawn,'pending_cards':waiting[:3],",
  'private_status_metadata')
 g=items[GATE].decode('utf8')
 g=rep(g,
  " if not str(release.get('version','')).startswith('2026-11-05-stable'):\n  alerts.append('STABLE_RELEASE_NOT_PINNED')",
  """ if not (str(release.get('version','')).startswith(('2026-11-05-stable','2026-11-14-stable'))
         and release.get('acceptance') in (None,'PASS')):
  alerts.append('STABLE_RELEASE_NOT_PINNED')""",
  'current_guard_version')
 g=rep(g,
  """ for item in report.get('alerts',[]):
  if isinstance(item,dict):
   alerts.append('NEWS_HEALTH_ALERT_'+str(item.get('code','UNSPECIFIED'))[:60])""",
  """ for item in report.get('alerts',[]):
  if isinstance(item,dict):
   label=str(item.get('code','UNSPECIFIED'))[:60]
   if item.get('level')=='CRITICAL':
    alerts.append('NEWS_HEALTH_ALERT_'+label)
   elif item.get('level') in ('WARNING','UNKNOWN'):
    cautions.append('NEWS_HEALTH_ADVISORY_'+label)""",
  'warning_vs_critical')
 n=items[NOTICE].decode('utf8')
 n=rep(n,
  " notify=bool(key!=previous or (key and now-lastnotice>7200))",
  """ # Never suppress a NEW problem or recovery; retain 2h reminders for
 # genuine critical incidents. Unchanged noncritical notices at most daily.
 critical=any('CRITICAL' in code for code in errors)
 reminder=7200 if critical else 86400
 notify=bool(key!=previous or (key and now-lastnotice>reminder))""",
  'notification_cooldown')
 output={HEALTH:h.encode('utf8'),GATE:g.encode('utf8'),NOTICE:n.encode('utf8')}
 for name,body in output.items():compile(body,name,'exec')
 return output
def original():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 directory(O);directory(R)
 if any(p.is_symlink() for p in (PIN,LOCK,RELEASE,BEFORE,ARCHIVE,RECEIPT)):
  raise Stop('SYMLINK_REFUSED')
 if RELEASE.exists():raise Stop('RELEASE_ALREADY_EXISTS')
 raw=safe(PIN,60000)
 state=json.loads(raw)
 if state.get('schema')!='RG_NEWS_STABILITY_RELEASE_V1' or state.get('version')!=OLD_VERSION:
  raise Stop('PINNED_VERSION_CHANGED')
 if state.get('acceptance')!='PASS' or set(state.get('files',{}))!=set(KEY):
  raise Stop('PINNED_CONTENT_SET_CHANGED')
 if any(state['files'][n]!=h for n,h in OLD.items()):
  raise Stop('GUARD_SOURCE_EXPECTATION_CHANGED')
 items={}
 for name in KEY:
  b=safe(O/name)
  if sha(b)!=state['files'][name]:raise Stop('DRIFTED_MODULE_'+name)
  items[name]=b
 oldarchive=Path(state.get('last_known_good_archive',''))
 if oldarchive.parent!=R/'guard_repair_wm_20261114' or oldarchive.is_symlink():
  raise Stop('OLD_ARCHIVE_PATH_CHANGED')
 with tarfile.open(oldarchive,'r:gz') as tf:
  if set(tf.getnames())!=set(KEY):raise Stop('OLD_ARCHIVE_MEMBERS_CHANGED')
  for name in KEY:
   m=tf.getmember(name)
   if not m.isfile() or sha(tf.extractfile(m).read())!=sha(items[name]):
    raise Stop('OLD_ARCHIVE_HASH_CHANGED_'+name)
 new=patches(items)
 return raw,state,items,new
def archive(dst,items):
 fd,tmp=tempfile.mkstemp(prefix='.rg_health_lkg_',dir=str(dst.parent),suffix='.tar.gz')
 os.close(fd)
 try:
  with tarfile.open(tmp,'w:gz') as tf:
   for name in KEY:
    raw=items[name]
    m=tarfile.TarInfo(name);m.mode=0o600;m.uid=m.gid=0
    m.mtime=int(time.time());m.size=len(raw)
    tf.addfile(m,io.BytesIO(raw))
  os.chmod(tmp,0o600)
  with tarfile.open(tmp,'r:gz') as tf:
   if set(tf.getnames())!=set(KEY):raise Stop('NEW_ARCHIVE_MEMBERS')
   for name in KEY:
    if sha(tf.extractfile(name).read())!=sha(items[name]):
     raise Stop('NEW_ARCHIVE_HASH_'+name)
  os.replace(tmp,dst)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def candidate_selftests(new):
 if not PY.is_file() or PY.is_symlink():raise Stop('PINNED_RUNTIME_MISSING')
 for name,mark in ((HEALTH,'NEWS_RG_STABILITY_HEALTHCHECK_SELFTEST_PASS'),
                   (GATE,'NEWS_RG_STABLE5_OPERATIONAL_GATE_SELFTEST_PASS')):
  with tempfile.TemporaryDirectory(prefix='rg_monitor_candidate_') as td:
   p=Path(td)/name;p.write_bytes(new[name])
   cp=subprocess.run([str(PY),str(p),'selftest'],capture_output=True,text=True,timeout=25)
   if cp.returncode or mark not in cp.stdout:raise Stop('SELFTEST_FAILURE_'+name)
def acceptance():
 cp=subprocess.run([str(PY),str(O/'news_rg_guarded_release_v1.py'),'force-check'],
                    capture_output=True,text=True,timeout=180)
 if cp.returncode:raise Stop('GUARD_ACCEPTANCE_FAILED')
 try:out=json.loads(cp.stdout.strip().splitlines()[-1])
 except (ValueError,IndexError):raise Stop('GUARD_OUTPUT_INVALID')
 if out.get('status')!='STABLE_ACCEPTANCE_PASS':
  raise Stop('GUARD_RESTORED_OR_FAILED_'+str(out.get('status','UNKNOWN')))
 return out
def post_qa():
 cp=subprocess.run([str(PY),str(O/HEALTH),'check'],capture_output=True,text=True,timeout=30)
 if cp.returncode not in (0,1,2):raise Stop('HEALTHCHECK_FAILED')
 rep=json.loads(cp.stdout)
 priv=rep.get('private') or {}
 if priv.get('uncertain_old_reconcile',0)<2 or priv.get('uncertain_recent_critical',-1)!=0:
  raise Stop('UNCERTAIN_PRIVATE_CLASSIFICATION_CHANGED')
 if any(x.get('code')=='PRIVATE_SEND_UNCERTAIN' and x.get('level')=='CRITICAL'
       for x in rep.get('alerts',[])):
  raise Stop('LEGACY_PRIVATE_CRITICAL_STILL_PRESENT')
 cp=subprocess.run([str(PY),str(O/GATE),'check'],capture_output=True,text=True,timeout=45)
 if cp.returncode not in (0,2):raise Stop('OPERATIONAL_CHECK_FAILED')
 g=json.loads(cp.stdout)
 if 'STABLE_RELEASE_NOT_PINNED' in g.get('alerts',[]):
  raise Stop('NEW_PIN_REJECTED')
 if any('PRIVATE_SEND_UNCERTAIN' in s for s in g.get('alerts',[])):
  raise Stop('UNCERTAIN_IN_CRITICAL_ALERTS')
 return {'health_status':rep.get('status'),'gate_status':g.get('status'),
         'private_old_uncertain':priv.get('uncertain_old_reconcile'),
         'private_recent_uncertain':priv.get('uncertain_recent_critical'),
         'private_http_rejected':priv.get('http_rejected_no_retry'),
         'operational_alerts':g.get('alerts',[]),
         'operational_advisories':g.get('advisories',[])}
def locked():
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 return fd
def install():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 fd=locked()
 try:
  before,meta,items,new=original()
  candidate_selftests(new)
  directory(RELEASE,create=True)
  atomic(BEFORE,before)
  if safe(BEFORE,60000)!=before:raise Stop('STATE_BACKUP_FAILED')
  for name in OLD:
   atomic(RELEASE/('before_'+name),items[name])
   if sha(safe(RELEASE/('before_'+name)))!=OLD[name]:raise Stop('MODULE_BACKUP_FAILED')
  installed=[]
  try:
   for name,data in new.items():
    installed.append(name)
    atomic(O/name,data,stat.S_IMODE((O/name).stat().st_mode))
    if sha(safe(O/name))!=sha(data):raise Stop('INSTALL_DRIFT_'+name)
   full=dict(items);full.update(new)
   archive(ARCHIVE,full)
   state=dict(meta)
   state['version']=NEW_VERSION
   state['installed_at']=int(time.time())
   state['prior_archive']=meta['last_known_good_archive']
   state['last_known_good_archive']=str(ARCHIVE)
   state['files']=dict(meta['files'])
   state['files'].update({k:sha(v) for k,v in new.items()})
   state['acceptance']='PASS'
   state['health_monitor_release']='RG_NEWS2_HEALTH_NO_SPAM_20261114'
   atomic(PIN,(json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
   # Must check all 18 components with the existing guard. Guard itself
   # will restore on failure; our exception handler verifies rollback.
   # Do not hold guard lock while running its force-check (same lock).
  except Exception:
   for name in reversed(installed):
    atomic(O/name,items[name],stat.S_IMODE((O/name).stat().st_mode))
   atomic(PIN,before)
   raise
 finally:os.close(fd)
 # Run acceptance after releasing lock, never under guard lock.
 try:
  accepted=acceptance()
  qa=post_qa()
 except Exception:
  rollback_failed=False
  fd=locked()
  try:
   for name,old in items.items():
    if name in OLD:
     atomic(O/name,old,stat.S_IMODE((O/name).stat().st_mode))
   atomic(PIN,before)
   if safe(PIN,60000)!=before or any(sha(safe(O/n))!=h for n,h in OLD.items()):
    rollback_failed=True
  finally:os.close(fd)
  if rollback_failed:raise Stop('POST_QA_FAILED_ROLLBACK_UNVERIFIED')
  raise Stop('POST_QA_FAILED_ROLLED_BACK')
 rec={'status':'APPLIED_QA_PASS','release':'RG_NEWS2_HEALTH_NO_SPAM_20261114',
      'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'old_version':OLD_VERSION,'new_version':NEW_VERSION,'updated_hashes':{k:sha(v) for k,v in new.items()},
      'modules_pinned':len(KEY),'backup_verified':True,
      'guard_acceptance':accepted.get('status'),'health_qa':qa,
      'telegram_api_calls_during_install':0,'publications_during_install':0,
      'historical_private_receipts_preserved':True}
 atomic(RECEIPT,(json.dumps(rec,sort_keys=True)+'\n').encode('utf8'))
 return rec
def selftest():
 assert len(OLD)==3 and len(KEY)==18
 assert all(len(h)==64 for h in OLD.values())
 assert R in PIN.parents and OLD_VERSION!=NEW_VERSION
 print('NEWS2_HEALTH_MONITOR_ATOMIC_RELEASE_SELFTEST_PASS')
if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args==['preflight']:
   before,old,items,new=original()
   candidate_selftests(new)
   print(json.dumps({'status':'PREFLIGHT_PASS','files_checked':len(items),
    'patched_modules':list(new),'new_hashes':{k:sha(v) for k,v in new.items()},
    'telegram_calls':0,'publications':0}))
  elif args==['apply']:print(json.dumps(install(),sort_keys=True))
  else:raise Stop('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
    'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
