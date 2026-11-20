#!/usr/bin/env python3
"""NEWS2 ten-point protected operational batch. Private, no Telegram calls.
--apply: safe footer-only source fix, snapshots and real offline acceptance.
Does not deploy Cloudflare, publish or change release-protected files.
"""
import ast,collections,datetime as dt,hashlib,json,os,pathlib,re,subprocess,sys,tarfile,tempfile,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=R/'operator';REL=O/'news_rg_stability_releases_v1'
MAN=REL/'pinned_release_v1.json';POLL=O/'news_rg_poll_moderation_v1.py'
INTAKE=O/'news_rg_manual_link_intake_v1.py';RETRY=O/'news_rg_manual_retry_v1.py'
FOOTER='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ РАША ГУДБАЙ'
OLD='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ'
URL='https://links.rginfoua.pp.ua/'
SHA_POLL='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
SCHEDULE=O/'news_rg_callback_scheduled_state_v1.json'
STABLE=O/'news_rg_stable5_operational_status_v1.json'
HEALTH=O/'news_rg_health_control_state_v1.json'
PILOT=REL/'rg_poll_private_pilot_receipt.json'
TARGETS=['news_rg_project_footer_v1.py','news_rg_organic_post_v1.py',
'news_rg_youtube_top_schedule_v1.py','rg_shorts_v3.py','news_rg_alert_24h_cleanup_v1.py']
NEWS='https://t.me/polit1humor/14293'
def js(p,limit=500000):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return {}
  x=json.loads(p.read_text('utf8'))
  return x if isinstance(x,dict) else {}
 except (OSError,ValueError,UnicodeError):return {}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def source(p):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>300000:return ''
  return p.read_text('utf8')
 except (OSError,UnicodeError):return ''
def check(code,ok,details=None):
 out['checks'][code]={'status':'PASS' if ok else 'ACTION_REQUIRED','details':details}
def atomic(p,b):
 fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.footer_')
 try:
  os.fchmod(fd,p.stat().st_mode&0o777)
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def backup(paths):
 folder=REL/'tenpoint_backups'
 if folder.is_symlink():raise RuntimeError('BACKUP_DIR_SYMLINK')
 folder.mkdir(mode=0o700,parents=True,exist_ok=True)
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 p=folder/('tenpoint_'+stamp+'.tar.gz')
 if p.exists():raise RuntimeError('BACKUP_COLLISION')
 with tarfile.open(p,'x:gz') as tf:
  for f in dict.fromkeys(paths):
   if f.is_file() and not f.is_symlink():
    tf.add(f,arcname=str(f.relative_to(R)),recursive=False)
 os.chmod(p,0o600)
 return p
def pytest(p,expected,timeout=20):
 if not p.is_file():return 'MISSING'
 try:
  cp=subprocess.run([sys.executable,str(p),'selftest'],capture_output=True,text=True,timeout=timeout)
  return 'PASS' if cp.returncode==0 and expected in cp.stdout else 'FAIL'
 except (subprocess.TimeoutExpired,OSError):return 'TIMEOUT_OR_EXEC_ERROR'
def run():
 global out
 out={'schema':'RG_NEWS2_TENPOINT_BATCH_V1',
      'time_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'requested_post':NEWS,'mode':'APPLY_SAFE' if '--apply' in sys.argv else 'AUDIT',
      'checks':{},'modifications':[],'telegram_calls':0,'publications':0,'new_pollers':0,
      'cloudflare_deploy':False,'public_poll_reenabled':False}
 if not R.is_dir():raise RuntimeError('ROOT_MISSING')
 require_root='--apply' in sys.argv
 if require_root and os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 manifest=js(MAN); protected=manifest.get('files',{})
 if not isinstance(protected,dict):protected={}
 guard=bool(len(protected)>=20 and protected.get(POLL.name)==SHA_POLL and sha(POLL)==SHA_POLL)
 integrity={n:sha(O/n)==h for n,h in protected.items() if (O/n).is_file() and not (O/n).is_symlink()}
 guard=guard and len(integrity)==len(protected) and all(integrity.values())
 check('05_pinned_release_integrity',guard,{'protected_files':len(protected),'verified_hashes':sum(integrity.values()),'version':manifest.get('version','unknown')})
 if not guard:out['operation_blocked']='RELEASE_INTEGRITY_FAILURE'
 a=source(INTAKE);b=source(RETRY)
 name_veto=('if source_requires_satire_review(link):' in a and 'if False and source_requires_satire_review(link):' not in a)
 retry_veto="if m.source_requires_satire_review(url):\n  return {'status':'SATIRE_REVIEW_REQUIRED'}" in b
 check('06_satire_source_name_veto',bool(a and b and not name_veto and not retry_veto),
       {'source_only_veto_active':name_veto or retry_veto,'post_content_not_factually_verified':True})
 check('08_duplicate_link_guards',all(t in a for t in
       ('MANUAL_LINK_ALREADY_STAGED_NO_RETRY','MANUAL_LINK_PREVIOUSLY_PUBLISHED_NO_RETRY','MANUAL_LINK_RETRY_ALREADY_RUNNING')))
 media=('classify_public_post_media' in a and 'VIDEO_SOURCE_NOT_VERIFIED_NO_PHOTO_SUBSTITUTION' in a)
 check('07_original_media_protection',media,{'real_media_delivery_test':'NOT_EXECUTED'})
 age=round(time.time()-SCHEDULE.stat().st_mtime) if SCHEDULE.is_file() else None
 c,s,h=js(SCHEDULE),js(STABLE),js(HEALTH)
 cbok=c.get('second_poller') is False and isinstance(c.get('offset_after'),int) and age is not None and 0<=age<=240
 check('02_callback_worker_live',cbok,{'age_seconds':age,'offset':c.get('offset_after'),'stable_status':s.get('status'),'health_status':h.get('status')})
 cbsource=source(O/'rg_news2_p31_guarded_callback_once.py')
 callback_receipt=('answerCallbackQuery' in cbsource and isinstance(js(PILOT),dict))
 check('03_callback_ack_real_receipt',False,{'source_includes_ack_api':callback_receipt,'real_ack_confirmed':False,
       'action':'NEED_REAL_ACK_RECEIPT_WITHOUT_SECOND_POLLER'})
 names=('front','Не знайдено в доступній публічній стрічці')
 front_candidates=[]
 for folder in (R,O):
  for p in folder.iterdir():
   if not p.is_file() or p.is_symlink() or p.suffix not in ('.py','.js','.json'):continue
   v=source(p)
   if 'front' in v and ('публічн' in v or 'PUBLIC_FEED' in v or 'FRONT' in v or 'front:' in v):
    front_candidates.append(str(p.relative_to(R)))
 check('01_front_feed_separation',False,{'files_to_investigate':front_candidates[:24],
   'current_manual_reception_contains_front':('front' in a),'action':'NEED_ROUTE_SPECIFIC_PATCH'})
 cloudflare_refs=[]
 for p in (R/'cloudflare-content-hub',O/'cloudflare-content-hub'):
  if p.is_dir():cloudflare_refs.append(str(p.relative_to(R)))
 check('04_cloudflare_live_deploy',False,{'local_source_directories':cloudflare_refs,
   'live_build_sha_verified':False,'action':'VERIFY_REAL_DEPLOY_AND_HEALTH_NO_PUBLIC_TEST'})
 footer_files=[];patches=[]
 pattern=re.compile(re.escape(OLD)+r'(?!\s+РАША\s+ГУДБАЙ)')
 for name in TARGETS:
  for directory in (R,O):
   p=directory/name;v=source(p)
   if not v:continue
   ct=len(pattern.findall(v))
   footer_files.append({'path':str(p.relative_to(R)),'old_occurrences':ct,'pinned':p.name in protected})
   if ct and p.name not in protected:
    patched=pattern.sub(FOOTER,v)
    ast.parse(patched,filename=str(p))
    patches.append((p,v.encode('utf8'),patched.encode('utf8')))
 footer_ok=not any(x['old_occurrences'] for x in footer_files)
 check('09_footer_exact',footer_ok,{'files':footer_files,'required_text':FOOTER,'destination':URL})
 if require_root and guard:
  snapshots=[MAN,INTAKE,RETRY,POLL,SCHEDULE,STABLE,HEALTH,PILOT]
  snapshots.extend(p for p,_,_ in patches)
  snap=backup(snapshots)
  out['backup']=str(snap)
  done=[]
  try:
   for p,old,new in patches:
    atomic(p,new);done.append((p,old))
    ast.parse(p.read_text('utf8'))
    if p.read_bytes()!=new:raise RuntimeError('FOOTER_VERIFY_FAILED')
   if any(sha(O/n)!=h for n,h in protected.items()):raise RuntimeError('PINNED_DRIFT_AFTER_PATCH')
   out['modifications']=[str(p.relative_to(R)) for p,_,_ in patches]
   if patches:
    check('09_footer_exact',True,{'patched':out['modifications'],'backup':snap.name,'protected_unchanged':True})
  except Exception:
   for p,old in reversed(done):atomic(p,old)
   raise
 tests={}
 for p,token in (
 ('news_rg_manual_link_intake_v1.py','NEWS_RG_MANUAL_LINK_INTAKE_SELFTEST_PASS'),
 ('news_rg_manual_retry_v1.py','MANUAL_RETRY_SELFTEST_PASS'),
 ('news_rg_poll_moderation_v1.py','RG_NEWS2_POLL_MODERATION_SELFTEST_PASS'),
 ('news_rg_editorial_callbacks_v1.py','NEWS_RG_EDITORIAL_CALLBACK_SELFTEST_PASS'),
 ('news_rg_durable_private_sender_v1.py','NEWS_RG_DURABLE_PRIVATE_MULTIPART_SELFTEST_PASS')):
  if require_root and guard:tests[p]=pytest(O/p,token)
  else:tests[p]='NOT_RUN'
 check('10_monitoring_selftests',bool(tests and all(v=='PASS' for v in tests.values())),tests)
 # Only write the report under the root-owned backup after safe batch; no public send.
 if require_root and guard:
  folder=REL/'tenpoint_backups'
  dest=folder/'latest_report.json'
  fd,tmp=tempfile.mkstemp(dir=folder,prefix='.tenpoint_report_')
  with os.fdopen(fd,'w',encoding='utf8') as f:
   os.fchmod(f.fileno(),0o600)
   json.dump(out,f,ensure_ascii=False,indent=2)
   f.flush();os.fsync(f.fileno())
  os.replace(tmp,dest)
 out['summary']={'pass':sum(x['status']=='PASS' for x in out['checks'].values()),
                 'action_required':sum(x['status']!='PASS' for x in out['checks'].values()),
                 'all_ten_verified':all(x['status']=='PASS' for x in out['checks'].values())}
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:run()
 except Exception as exc:
  print(json.dumps({'status':'SAFE_STOP','reason':str(exc)[:200],
    'publications':0,'telegram_calls':0,'new_pollers':0},ensure_ascii=False))
  sys.exit(2)
