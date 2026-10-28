#!/usr/bin/env python3
"""NEWS RG: guarded video-aware manual intake upgrade.

Change exactly three live scripts and create one local watermark handoff module.
Keep sole NAS Telegram update owner unchanged, public publication DISABLED,
DSM job unchanged, existing private photo review untouched. Create backups,
test syntax and offline selftests, restore all touched scripts on failure.
"""
import os,sys,ast,json,time,stat,pathlib,hashlib,subprocess,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
WORKER=O/'rg_news2_p31_guarded_callback_once.py'
OWNER=O/'callback_v29.py'
ACT=O/'news_rg_manual_link_activation_v1.json'
FILES={
 'intake':('news_rg_manual_link_intake_v1.py','/tmp/news_rg_v3_intake.py'),
 'sender':('news_rg_durable_private_sender_v1.py','/tmp/news_rg_v3_sender.py'),
 'callbacks':('news_rg_editorial_callbacks_v1.py','/tmp/news_rg_v3_callbacks.py'),
 'watermark':('news_rg_video_watermark_handoff_v1.py','/tmp/news_rg_v3_watermark.py'),
}
BACKUP=O/'news_rg_manual_original_video_before_v3'
def fail(reason):raise RuntimeError(reason)
def file_read(path,max_bytes=110000):
 if path.is_symlink() or not path.is_file() or path.stat().st_size>max_bytes:
  fail('MISSING_OR_UNSAFE_'+path.name)
 return path.read_text('utf8')
def atomic(path,body,mode,owner=None):
 fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix='.newsrg_video_v3_')
 try:
  with os.fdopen(fd,'wb') as out:
   os.fchmod(out.fileno(),mode)
   if owner:os.fchown(out.fileno(),owner[0],owner[1])
   out.write(body);out.flush();os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def verify():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if B.is_symlink() or O.is_symlink() or not B.is_dir() or not O.is_dir():
  fail('OPERATOR_BASE_UNSAFE')
 for p in (WORKER,OWNER,ACT):file_read(p)
 worker=file_read(WORKER)
 if worker.count('# NEWS_RG_MANUAL_LINK_SINGLE_OWNER_V1')!=1 or worker.count("['callback_query','message']")!=1:
  fail('SINGLE_OWNER_ROUTE_CHANGED')
 if "WORKER=O/'rg_news2_p31_guarded_callback_once.py'" not in file_read(OWNER):
  fail('CALLBACK_OWNER_CHANGED')
 gate=json.loads(file_read(ACT))
 if gate.get('status')!='ACTIVE' or gate.get('schema')!='NEWS_RG_MANUAL_LINK_ACTIVATION_V1':
  fail('MANUAL_LINK_GATE_NOT_ACTIVE')
 if BACKUP.exists() or BACKUP.is_symlink():fail('BACKUP_CONFLICT')
 files={}
 for key,(name,stage) in FILES.items():
  source=pathlib.Path(stage)
  new=file_read(source)
  ast.parse(new)
  dest=O/name
  existing=None if key=='watermark' and not dest.exists() else file_read(dest)
  files[key]={'path':dest,'source':new,'old':existing}
 if files['watermark']['old'] is not None:fail('WATERMARK_MODULE_ALREADY_EXISTS')
 old=files['intake']['old']
 if (not old or 'def from_canonical' not in old or 'def prepare_ukrainian' not in old
    or 'def classify_public_post_media' in old):
  fail('INTAKE_IS_NOT_LAST_KNOWN_PHOTO_VERSION')
 before=files['sender']['old']
 if (not before or "url='https://api.telegram.org/bot'+bot_token+'/sendPhoto'" not in before
    or 'def pack_original_video' in before):
  fail('SENDER_NOT_LAST_KNOWN_PHOTO_ONLY_VERSION')
 cb=files['callbacks']['old']
 if (not cb or 'EDITORIAL_ACCEPTED_NO_PUBLICATION' not in cb
    or '_watermark_after_video_accept' in cb):
  fail('CALLBACK_VERSION_CHANGED')
 if not all(t in files['intake']['source'] for t in
   ('def classify_public_post_media','def probe_video','original_video_url','NEWS_RG_MANUAL_LINK_INTAKE_V1')):
  fail('NEW_INTAKE_CONTRACT_MISSING')
 if not all(t in files['sender']['source'] for t in
   ('def pack_original_video','VIDEO_ACK_MISSING_FILE_ID','sendVideo','watermark_required')):
  fail('NEW_SENDER_CONTRACT_MISSING')
 if '_watermark_after_video_accept' not in files['callbacks']['source']:
  fail('NEW_CALLBACK_CONTRACT_MISSING')
 if 'WAITING_FOR_VERIFIED_WATERMARK_BRIDGE' not in files['watermark']['source']:
  fail('NEW_WATERMARK_GUARD_MISSING')
 if 'getUpdates' in ast.dump(ast.parse(files['watermark']['source'])):
  fail('NEW_WATERMARK_POLLER_FORBIDDEN')
 for key in ('intake','callbacks','watermark'):
  proc=subprocess.run(['/usr/bin/python3',FILES[key][1]]+
    (['selftest'] if key!='callbacks' else []),
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,text=True)
  if proc.returncode or 'SELFTEST_PASS' not in proc.stdout:
   fail('STAGED_SELFTEST_FAILED_'+key)
 return files
def install():
 files=verify()
 BACKUP.mkdir(mode=0o700)
 os.chmod(BACKUP,0o700)
 touched=[]
 try:
  # Back up every original before any live module is replaced.
  for key in ('intake','sender','callbacks'):
   obj=files[key];old=obj['old'];dest=obj['path']
   backup=BACKUP/(dest.name+'.before')
   with backup.open('xb') as h:
    os.fchmod(h.fileno(),0o600)
    h.write(old.encode('utf8'));h.flush();os.fsync(h.fileno())
   if file_read(dest)!=old:fail('CONCURRENT_CHANGE_'+key)
  # Install data-only watermark handoff first; then callbacks/sender, intake last.
  for key in ('watermark','callbacks','sender','intake'):
   obj=files[key];dest=obj['path']
   if key=='watermark' and (dest.exists() or dest.is_symlink()):
    fail('CONCURRENT_NEW_WATERMARK_MODULE')
   mode=0o600 if key=='watermark' else stat.S_IMODE(dest.stat().st_mode)
   owner=None if key=='watermark' else (dest.stat().st_uid,dest.stat().st_gid)
   atomic(dest,obj['source'].encode('utf8'),mode,owner)
   touched.append(key)
   if file_read(dest)!=obj['source']:fail('POSTINSTALL_MISMATCH_'+key)
   ret=subprocess.run(['/usr/bin/python3','-m','py_compile',str(dest)],timeout=9)
   if ret.returncode:fail('POSTINSTALL_COMPILE_FAILED_'+key)
  for key in ('intake','callbacks','watermark'):
   ret=subprocess.run(['/usr/bin/python3',str(files[key]['path'])]+
    (['selftest'] if key!='callbacks' else []),
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,text=True)
   if ret.returncode or 'SELFTEST_PASS' not in ret.stdout:
    fail('POSTINSTALL_SELFTEST_FAILED_'+key)
  # We deliberately do not send Telegram messages or add Cloudflare jobs here.
  return {'status':'NEWS_RG_ORIGINAL_VIDEO_PRIVATE_REVIEW_INSTALLED',
   'private_video_send':'SUPPORTED_AFTER_NEW_MANUAL_LINK',
   'watermark_handoff':'LOCAL_DURABLE_QUEUE_ONLY',
   'cloudflare_delivery':'NOT_CONNECTED',
   'publication':'OFF','existing_callback_owner_unchanged':True,
   'new_pollers':0,'new_dsm_tasks':0,'telegram_calls_during_install':0,
   'originals_backed_up':3}
 except Exception:
  for key in reversed(touched):
   obj=files[key];dest=obj['path']
   try:
    if key=='watermark':
     if dest.is_file() and not dest.is_symlink() and file_read(dest)==obj['source']:
      dest.unlink()
    elif dest.is_file() and not dest.is_symlink() and file_read(dest)==obj['source']:
     mode=stat.S_IMODE(dest.stat().st_mode)
     owner=(dest.stat().st_uid,dest.stat().st_gid)
     atomic(dest,obj['old'].encode('utf8'),mode,owner)
   except (OSError,RuntimeError):
    pass
  raise
def selftest():
 assert set(FILES)=={'intake','sender','callbacks','watermark'}
 assert len(FILES)==4
 print('NEWS_RG_ORIGINAL_VIDEO_UPGRADER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:
   ff=verify()
   print(json.dumps({'status':'NEWS_RG_ORIGINAL_VIDEO_PREFLIGHT_PASS',
     'backup_needed':True,'new_pollers':0,'publications':0,
     'files_to_upgrade':len(ff),'worker_unchanged':True}))
  elif sys.argv[1:]==['install']:
   print(json.dumps(install(),ensure_ascii=False,sort_keys=True))
  else:fail('EXPECTED_SELFTEST_PREFLIGHT_INSTALL')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP',
    'reason':str(e)[:120] if isinstance(e,RuntimeError) else type(e).__name__,
    'publications':0,'pollers_started':0,'telegram_bot_calls':0}))
  sys.exit(2)
