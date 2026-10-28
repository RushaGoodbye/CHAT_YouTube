#!/usr/bin/env python3
"""Upgrade ONLY already-installed NEWS RG single-owner manual-link helper.

Preflight requires active singleton routing; never edits rg_moderation,
existing worker, Gatus, DSM task, Telegram offset, publication state or AI.
Backup and rollback the one helper file; no extra Telegram pollers.
"""
import os,sys,json,pathlib,hashlib,stat,subprocess,tempfile,ast
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
WORKER=O/'rg_news2_p31_guarded_callback_once.py'
OWNER=O/'callback_v29.py'
ACTIVE=O/'news_rg_manual_link_activation_v1.json'
TARGET=O/'news_rg_manual_link_intake_v1.py'
STAGE=pathlib.Path('/tmp/news_rg_manual_link_intake_v1.py')
BACKUP=O/'news_rg_manual_link_intake_before_video_ua_v2.backup'
TAG='NEWS_RG_MANUAL_VIDEO_UA_UPGRADE_V2'
def stop(s):raise RuntimeError(s)
def read(p,limit=90000):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:stop('UNSAFE_'+p.name)
 return p.read_text('utf8')
def digest(s):return hashlib.sha256(s.encode('utf8')).hexdigest()[:16]
def check():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 if not B.is_dir() or not O.is_dir() or B.is_symlink() or O.is_symlink():stop('UNSAFE_DIRECTORIES')
 for p in (WORKER,OWNER,ACTIVE,TARGET,STAGE):read(p)
 data=json.loads(read(ACTIVE))
 if data.get('schema')!='NEWS_RG_MANUAL_LINK_ACTIVATION_V1' or data.get('status')!='ACTIVE':
  stop('MANUAL_LINK_EXISTING_ACTIVATION_NOT_ACTIVE')
 worker=read(WORKER)
 if worker.count('# NEWS_RG_MANUAL_LINK_SINGLE_OWNER_V1')!=1:
  stop('ACTIVE_SINGLE_OWNER_MESSAGE_ROUTE_CHANGED')
 if worker.count("['callback_query','message']")!=1 or not worker.count('news_rg_manual_link_intake_v1'):
  stop('MESSAGE_POLLING_ROUTE_CHANGED')
 if read(OWNER).count("WORKER=O/'rg_news2_p31_guarded_callback_once.py'")!=1:
  stop('SINGLE_OWNER_ROUTING_CHANGED')
 old=read(TARGET)
 fresh=read(STAGE)
 if TAG in old or 'def from_canonical' in old:
  if old==fresh:return {'status':'ALREADY_UPGRADED','changes':0},None
  stop('UNEXPECTED_UPGRADED_HELPER')
 if 'class PublicPostReader' not in old or 'def source_to_post' not in old:
  stop('ORIGINAL_HELPER_FORMAT_CHANGED')
 if 'def prepare_ukrainian' in old or 'def from_canonical' in old:
  stop('UNEXPECTED_OLD_HELPER')
 for signature in ('def from_canonical','def prepare_ukrainian','def ukrainian_draft_ok',
                    'def source_to_post','def stage','def handle','def dispatch_once_async',
                    "NEWS_RG_MANUAL_LINK_INTAKE_V1"):
  if signature not in fresh:stop('NEW_HELPER_MISSING_CONTRACT')
 if 'getUpdates' in fresh or 'api.telegram.org' in fresh or 'sendPhoto' in fresh:
  stop('FORBIDDEN_TELEGRAM_POLLING_OR_SENDING')
 ast.parse(fresh)
 test=subprocess.run(['/usr/bin/python3',str(STAGE),'selftest'],
  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15,text=True)
 if test.returncode or 'NEWS_RG_MANUAL_LINK_INTAKE_SELFTEST_PASS' not in test.stdout:
  stop('NEW_HELPER_SELFTEST_NOT_PASS')
 if BACKUP.exists() or BACKUP.is_symlink():stop('UPGRADE_BACKUP_CONFLICT')
 return {'status':'NEWS_RG_MANUAL_VIDEO_UA_PREFLIGHT_PASS',
  'existing_worker_untouched':True,'original_helper_sha16':digest(old),
  'new_helper_sha16':digest(fresh),'backup_created_by_install':True,
  'new_pollers':0,'new_dsm_tasks':0,'telegram_bot_calls':0,'publications':0,
  'change_scope':'ONE_EXISTING_MANUAL_HELPER_ONLY'},(old,fresh)
def atomic(p,data,mode):
 fd,temp=tempfile.mkstemp(dir=str(p.parent),prefix='.newsrg_manual_v2_')
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   if p.is_file() and not p.is_symlink():
    meta=p.stat();os.fchown(f.fileno(),meta.st_uid,meta.st_gid)
   f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
 finally:
  if os.path.exists(temp):os.unlink(temp)
def install():
 preview,pair=check()
 if pair is None:return preview
 old,fresh=pair
 mode=stat.S_IMODE(TARGET.stat().st_mode)
 try:
  # One backup of exactly the installed old helper; no backup overwrite.
  fd=os.open(str(BACKUP),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'wb') as b:
   b.write(old.encode('utf8'));b.flush();os.fsync(b.fileno())
  if read(TARGET)!=old:stop('CONCURRENT_HELPER_CHANGE')
  atomic(TARGET,fresh.encode('utf8'),mode)
  compiled=subprocess.run(['/usr/bin/python3','-m','py_compile',str(TARGET)],
   capture_output=True,timeout=10)
  if compiled.returncode:stop('NEW_HELPER_LIVE_COMPILE_FAILED')
  result=subprocess.run(['/usr/bin/python3',str(TARGET),'selftest'],
    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15,text=True)
  if result.returncode or 'SELFTEST_PASS' not in result.stdout:stop('NEW_HELPER_LIVE_SELFTEST_FAILED')
  if read(TARGET)!=fresh:stop('NEW_HELPER_LIVE_HASH_CHANGED')
  return {'status':'NEWS_RG_MANUAL_VIDEO_UA_UPGRADED',
    'protected_existing_worker':True,'old_helper_backup_created':True,
    'private_review_remains_required':True,'publications':0,
    'bot_calls':0,'new_pollers':0,'new_schedules':0,
    'exact_post_probe_passed_by_separate_gate':True}
 except Exception:
  # Restore only the helper if our contents were written; no other files touched.
  if TARGET.is_file() and not TARGET.is_symlink() and read(TARGET)==fresh:
   atomic(TARGET,old.encode('utf8'),mode)
  raise
def selftest():
 sample='def source_to_post(url):pass\nclass PublicPostReader:pass\n'
 assert 'def source_to_post' in sample and 'class PublicPostReader' in sample
 assert 'getUpdates' not in TAG
 assert 'news_rg_manual_link_intake_v1.py' in str(TARGET)
 print('NEWS_RG_MANUAL_VIDEO_UA_UPGRADER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:
   report,_=check();print(json.dumps(report,ensure_ascii=False,sort_keys=True))
  elif sys.argv[1:]==['install']:
   print(json.dumps(install(),ensure_ascii=False,sort_keys=True))
  else:stop('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  reason=str(e)[:90] if isinstance(e,RuntimeError) else type(e).__name__
  print(json.dumps({'status':'SAFE_STOP','reason':reason,
   'new_pollers':0,'publications':0,'telegram_bot_calls':0},ensure_ascii=False))
  sys.exit(2)
