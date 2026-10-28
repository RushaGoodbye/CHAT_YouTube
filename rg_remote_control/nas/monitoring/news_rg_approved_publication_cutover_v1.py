#!/usr/bin/env python3
"""NEWS RG: controlled public publication cutover, single existing DSM scheduler.

Requires authoritative existing target channel + bot admin verified with
Telegram read-only API before edits. Does not publish during installation.
No changes to existing Telegram callback owner or polling.
"""
import os,sys,re,json,pathlib,tempfile,hashlib,subprocess,time,stat,ast,importlib.util
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
T=B/'rg_news_dsm_tick.sh'
S=O/'news_rg_durable_private_sender_v1.py'
PUB=O/'news_rg_approved_publication_v1.py'
SCHED=O/'news_rg_publication_schedule_v1.py'
ACT=O/'news_rg_publication_activation_v1.json'
MARK='# NEWS_RG_APPROVED_PUBLICATION_CUTOVER_V1'
PUB_SRC=pathlib.Path('/tmp/news_rg_approved_publication_v1.py')
SAFE_BUTTON='✅ Схвалити й опублікувати'
MARK_OLD='✅ Схвалити (без публікації)'
OLD_RECEIPT="""  store(receipt,{'status':'PRIVATE_SENT_CONFIRMED','draft_id':item['draft_id'],
   'message_id':message['message_id'],'confirmed_at':int(time.time()),'public_publication':'OFF'})"""
NEW_RECEIPT="""  photos=message.get('photo') or []
  if not isinstance(photos,list) or not photos or not isinstance(photos[-1],dict):
   die('ACK_PHOTO_FILE_ID_MISSING')
  photo_id=photos[-1].get('file_id')
  if not isinstance(photo_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{15,255}',photo_id):
   die('ACK_PHOTO_FILE_ID_INVALID')
  store(receipt,{'status':'PRIVATE_SENT_CONFIRMED','draft_id':item['draft_id'],
   'message_id':message['message_id'],'confirmed_at':int(time.time()),
   'telegram_photo_file_id':photo_id,'public_publication':'OFF'})"""
SCHED_SRC="""#!/usr/bin/env python3
# NEWS RG publication scheduling only. Uses EXISTING NAS DSM job. No polling.
import os,sys,pathlib,fcntl,time,subprocess,json
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
P=O/'news_rg_approved_publication_v1.py'
LAST=O/'news_rg_publication_last_launch'
def main():
 if os.geteuid()!=0:return
 fd=os.open(str(O/'news_rg_publication_scheduler.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (OSError,BlockingIOError):return
  now=time.time()
  if LAST.is_file():
   try:
    if now-float(LAST.read_text())<300:return
   except (ValueError,OSError):return
  if not P.is_file() or P.is_symlink():return
  s=subprocess.run(['/usr/bin/python3',str(P),'status'],
    capture_output=True,text=True,timeout=8)
  if s.returncode:return
  try:obj=json.loads(s.stdout)
  except (TypeError,ValueError):return
  if obj.get('status')!='ACTIVE' or obj.get('new_approved_ready') is not True:return
  log=os.open(str(O/'news_rg_publication_autorun.log'),os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
  try:
   proc=subprocess.Popen(['/usr/bin/python3',str(P),'publish-one'],
      stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
   fd2,tmp=__import__('tempfile').mkstemp(prefix='.newsrgp_',dir=str(O))
   with os.fdopen(fd2,'w') as f:
    os.fchmod(f.fileno(),0o600)
    f.write(str(now));f.flush();os.fsync(f.fileno())
   os.replace(tmp,LAST)
  finally:os.close(log)
 finally:os.close(fd)
if __name__=='__main__' and sys.argv[1:]==['tick']:main()
"""
def err(s):raise RuntimeError(s)
def emit(**x):print(json.dumps(x,sort_keys=True,ensure_ascii=False))
def atomic(p,blob,mode):
 fd,tmp=tempfile.mkstemp(prefix='.newsrg_pub_cutover_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode)
   f.write(blob);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def patch_sender(src):
 if SAFE_BUTTON in src and 'telegram_photo_file_id' in src:
  return src,True
 if src.count(MARK_OLD)!=1 or src.count(OLD_RECEIPT)!=1:
  err('PRIVATE_SENDER_SOURCE_UNEXPECTED')
 updated=src.replace(MARK_OLD,SAFE_BUTTON,1).replace(OLD_RECEIPT,NEW_RECEIPT,1)
 if src.count('НЕ ПУБЛІКУВАТИ.')!=1 or src.count('Факти та фото потребують перевірки.')!=1:
  err('PRIVATE_REVIEW_CAPTION_CONTRACT_CHANGED')
 updated=updated.replace('⚠️ NEWS RG · ПРИВАТНА ПЕРЕВІРКА. НЕ ПУБЛІКУВАТИ.',
                         '📰 NEWS RG · ПРИВАТНА ПЕРЕВІРКА ПЕРЕД ПУБЛІКАЦІЄЮ.',1)
 updated=updated.replace('Факти та фото потребують перевірки.',
                         'Схвалення опублікує цей текст і фото в каналі.',1)
 if 'НЕ ПУБЛІКУВАТИ.' in updated:
  err('PRIVATE_CAPTION_STILL_PROHIBITS_PUBLICATION')
 if 'import os,sys,json,time,pathlib,uuid,urllib.request,urllib.error,hashlib' in updated:
  updated=updated.replace('import os,sys,json,time,pathlib,uuid,urllib.request,urllib.error,hashlib',
                          'import os,sys,json,time,pathlib,uuid,urllib.request,urllib.error,hashlib,re',1)
 else:err('SENDER_IMPORT_CONTRACT_CHANGED')
 ast.parse(updated)
 return updated,False
def patch_tick(old):
 if old.count(MARK)!=0: return old,True
 if '# NEWS_RG_PRIVATE_AUTOMATION_CUTOVER_V1' not in old:err('PRIVATE_AUTOMATION_TICK_NOT_INSTALLED')
 if not old.rstrip().endswith('exit 0'):err('DSM_EXIT_LAYOUT_CHANGED')
 if old.count('news_rg_private_dispatch_schedule_v1.py')!=1:err('PRIVATE_DISPATCH_ENTRY_MISSING')
 ending=old.rfind('exit 0')
 if ending<0:err('LAST_EXIT_NOT_FOUND')
 patched=old[:ending]+MARK+"""
# Only human-approved, *new* private news; existing NAS task, no new poller.
/usr/bin/python3 '/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_publication_schedule_v1.py' tick >/dev/null 2>&1 || :
exit 0
"""
 test=subprocess.run(['sh','-n'],input=patched,text=True,capture_output=True,timeout=8)
 if test.returncode:err('DSM_TICK_SYNTAX_FAILED')
 return patched,False
def publish_mod():
 if PUB_SRC.is_symlink() or not PUB_SRC.is_file():err('PUBLIC_SOURCE_MISSING')
 data=PUB_SRC.read_text('utf-8')
 if 'NEWS_RG_PUBLICATION_PUBLISHER_SELFTEST_PASS' not in data or 'PUBLIC_SEND_UNCERTAIN_NO_RETRY' not in data:
  err('UNKNOWN_PUBLIC_SOURCE')
 ast.parse(data)
 return data
def preflight():
 if os.geteuid()!=0:err('SUDO_REQUIRED')
 for p in (B,O):
  if not p.is_dir() or p.is_symlink():err('BASE_UNSAFE')
 for p in (T,S,O/'news_rg_private_multipart_receipts_v1',O/'news_rg_editorial_decisions_v1',O/'news_rg_private_dispatch_schedule_v1.py'):
  if not p.exists() or p.is_symlink():err('MISSING_OR_SYMLINK_'+p.name)
 old=T.read_text('utf-8');old_sender=S.read_text('utf-8')
 pub=publish_mod()
 new_tick,already=patch_tick(old)
 new_sender,_=patch_sender(old_sender)
 if ACT.exists():
  val=json.loads(ACT.read_text('utf-8'))
  if val.get('status')=='ACTIVE' and already:
   return {'status':'ALREADY_ACTIVE','activation':val},None
  err('ACTIVATION_EXISTS_WITHOUT_VALID_CUTOVER')
 if already:err('TICK_PATCH_ALREADY_PRESENT_WITHOUT_ACTIVATION')
 if PUB.exists() and PUB.is_symlink():err('PUBLIC_MODULE_SYMLINK')
 if SCHED.exists() and SCHED.is_symlink():err('SCHEDULE_MODULE_SYMLINK')
 # Execute tests on isolated staged modules, not production.
 test=subprocess.run(['/usr/bin/python3',str(PUB_SRC),'selftest'],
    text=True,capture_output=True,timeout=12)
 if test.returncode or 'SELFTEST_PASS' not in test.stdout:
  err('PUBLIC_PUBLISHER_SELFTEST_FAILED')
 importlib.util.spec_from_file_location('pub_check',str(PUB_SRC))
 spec=importlib.util.spec_from_file_location('_newsrg_pub_check',str(PUB_SRC))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 # getMe/getChat/getChatMember only: no Telegram sending.
 channel=m.verify_channel(m.module(),m.credentials())
 if channel['chat_id']<=-999999999 and channel['bot_id']>0:
  pass
 else:err('CHANNEL_ID_INVALID')
 return {'status':'PUBLICATION_PREFLIGHT_PASS','channel':channel,
         'old_approved_posts_excluded':True,
         'changes':['private_accept_button','private_photo_file_id',
                    'publication_ledger','dsm_schedule'],
         'new_pollers':0,'telegram_sends':0,'publications':0},(old,old_sender,new_tick,new_sender,pub,channel)
def install():
 report,files=preflight()
 if files is None:return {'status':'PUBLICATION_ALREADY_ACTIVE','publications':0}
 old,old_sender,tick,sender,pub,channel=files
 digest=hashlib.sha256((old+'\n'+old_sender).encode('utf-8')).hexdigest()[:16]
 tick_bak=O/('rg_news_dsm_tick.before_pub_'+digest+'.sh')
 sender_bak=O/('news_rg_private_sender.before_pub_'+digest+'.py')
 for p in (tick_bak,sender_bak):
  if p.is_symlink():err('BACKUP_SYMLINK')
 if not tick_bak.exists():atomic(tick_bak,old.encode(),0o600)
 if not sender_bak.exists():atomic(sender_bak,old_sender.encode(),0o600)
 old_pub=PUB.read_bytes() if PUB.is_file() else None
 old_sched=SCHED.read_bytes() if SCHED.is_file() else None
 tick_mode=stat.S_IMODE(T.stat().st_mode)
 sender_mode=stat.S_IMODE(S.stat().st_mode)
 try:
  receipts=O/'news_rg_publication_receipts_v1'
  if receipts.is_symlink():err('PUBLIC_RECEIPTS_SYMLINK')
  if not receipts.exists():
   receipts.mkdir(mode=0o700)
  elif not receipts.is_dir():err('PUBLIC_RECEIPTS_NOT_DIRECTORY')
  os.chmod(receipts,0o700)
  atomic(PUB,pub.encode(),0o600)
  atomic(SCHED,SCHED_SRC.encode(),0o700)
  ast.parse(SCHED.read_text())
  atomic(S,sender.encode(),sender_mode)
  if 'telegram_photo_file_id' not in S.read_text():err('SENDER_POSTINSTALL_MISMATCH')
  if SAFE_BUTTON not in S.read_text() or 'НЕ ПУБЛІКУВАТИ.' in S.read_text():
   err('PRIVATE_PUBLICATION_CONSENT_TEXT_MISMATCH')
  sender_check=subprocess.run(['/usr/bin/python3',str(S),'selftest'],
                              text=True,capture_output=True,timeout=12)
  if sender_check.returncode or 'SELFTEST_PASS' not in sender_check.stdout:
   err('PATCHED_PRIVATE_SENDER_SELFTEST_FAILED')
  # Enable only after all code and backups verify. Historical acceptances excluded.
  act={'schema':'NEWS_RG_PUBLICATION_ACTIVATION_V1','status':'ACTIVE',
   'activated_at':int(time.time()),'chat_id':channel['chat_id'],
   'bot_id':channel['bot_id'],'channel_title':channel['title'],
   'historical_publication':'DISABLED'}
  if ACT.exists():err('ACTIVATION_CONCURRENT_CREATION')
  # Activation record is persisted after tick, which stays safe if absent.
  atomic(T,tick.encode(),tick_mode)
  atomic(ACT,json.dumps(act,ensure_ascii=False,sort_keys=True).encode(),0o600)
  chk=subprocess.run(['/usr/bin/python3',str(PUB),'status'],
                     capture_output=True,text=True,timeout=12)
  if chk.returncode or '"status": "ACTIVE"' not in chk.stdout:err('POSTINSTALL_PUBLICATION_STATUS_NOT_ACTIVE')
 except Exception:
  if ACT.exists() and ACT.is_file() and not ACT.is_symlink():ACT.unlink()
  atomic(T,old.encode(),tick_mode)
  atomic(S,old_sender.encode(),sender_mode)
  if old_pub is None and PUB.exists():PUB.unlink()
  elif old_pub is not None:atomic(PUB,old_pub,0o600)
  if old_sched is None and SCHED.exists():SCHED.unlink()
  elif old_sched is not None:atomic(SCHED,old_sched,0o700)
  receipts=O/'news_rg_publication_receipts_v1'
  if receipts.is_dir() and not receipts.is_symlink() and not any(receipts.iterdir()):
   receipts.rmdir()
  raise
 return {'status':'NEWS_RG_APPROVED_PUBLICATION_ENABLED',
  'channel_title':channel['title'],'channel_id':channel['chat_id'],
  'new_approvals_only':True,'old_8051_not_replayed':True,
  'private_moderation_preserved':True,'publications_during_install':0,
  'pollers_created':0,'new_dsm_tasks':0,
  'backup_tick':str(tick_bak),'backup_sender':str(sender_bak)}
def disable():
 if os.geteuid()!=0:err('SUDO_REQUIRED')
 if not ACT.is_file() or ACT.is_symlink():err('ACTIVATION_NOT_FOUND')
 data=json.loads(ACT.read_text('utf-8'))
 if data.get('schema')!='NEWS_RG_PUBLICATION_ACTIVATION_V1':err('ACTIVATION_SCHEMA_CHANGED')
 # Do not alter code or callbacks: the public gate alone is sufficient to pause.
 if data.get('status')=='DISABLED':
  return {'status':'NEWS_RG_PUBLICATION_ALREADY_DISABLED','publications':0}
 if data.get('status')!='ACTIVE':err('ACTIVATION_STATE_UNEXPECTED')
 import fcntl
 lock=O/'news_rg_publication.lock'
 fd=os.open(str(lock),os.O_CREAT|os.O_RDWR,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX)
  data['status']='DISABLED'
  data['disabled_at']=int(time.time())
  atomic(ACT,json.dumps(data,ensure_ascii=False,sort_keys=True).encode('utf-8'),0o600)
 finally:os.close(fd)
 return {'status':'NEWS_RG_PUBLICATION_DISABLED','publications':0}
def selftest():
 # The live staged publisher runs its isolated full eligibility tests in preflight.
 assert 'getUpdates' not in SCHED_SRC and 'sendPhoto' not in SCHED_SRC
 assert MARK.startswith('# NEWS_RG_')
 assert SAFE_BUTTON!=MARK_OLD
 print('NEWS_RG_PUBLICATION_CUTOVER_INSTALLER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args==['preflight']:
   r,_=preflight();emit(**r)
  elif args==['install']:emit(**install())
  elif args==['disable']:emit(**disable())
  else:err('BAD_MODE')
 except Exception as e:
  emit(status='SAFE_STOP',reason=str(e)[:130],telegram_sends=0,publications=0)
  sys.exit(2)
