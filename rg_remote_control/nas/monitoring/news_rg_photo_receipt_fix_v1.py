#!/usr/bin/env python3
"""Safe update of NEWS RG private sender photo acknowledgement and optional archive backfill.
Never sends Telegram messages, polls Telegram, modifies decisions or invokes publisher."""
import os,sys,ast,json,re,time,stat,pathlib,tempfile,hashlib,subprocess
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
LIVE=O/'news_rg_durable_private_sender_v1.py'
STAGED=pathlib.Path('/tmp/news_rg_durable_private_sender_v1.py')
KEY='f8ad241cbc38ffca55dc7f6f'
MESSAGE=8073
OLD="  if item_kind=='photo' and not message.get('photo'):\n   die('PHOTO_ACK_MISSING')"
NEW="  photo_id=None\n  if item_kind=='photo':"
NEW_FIELD="'telegram_photo_file_id':photo_id"
def report(**kw):print(json.dumps(kw,sort_keys=True))
def stop(reason):raise RuntimeError(reason)
def read(p,limit=200000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:stop('UNSAFE_'+p.name)
 return p.read_bytes()
def put(p,b,mode):
 fd,temp=tempfile.mkstemp(prefix='.news_rg_photo_fix_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),mode);f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(temp,str(p))
 finally:
  if os.path.exists(temp):os.unlink(temp)
def preflight():
 if os.geteuid()!=0:stop('SUDO_REQUIRED')
 old=read(LIVE);new=read(STAGED)
 a=old.decode('utf8');b=new.decode('utf8')
 ast.parse(a);ast.parse(b)
 if NEW not in b or NEW_FIELD not in b or 'PRIVATE_SENT_CONFIRMED' not in b:stop('STAGED_FIX_NOT_RECOGNIZED')
 if 'MAX_OUTSTANDING=20' not in b or "'original_video_file_id':" not in b:stop('STAGED_SENDER_CONTRACT_CHANGED')
 if a==b:return old,new,True
 if a.count(OLD)!=1 or NEW in a or NEW_FIELD in a:stop('LIVE_SENDER_UNEXPECTED')
 # Exact allowed change is new photo validation and new field; preserve every other byte.
 start=a.index(OLD);end=start+len(OLD)
 expected=a[:start]+b[b.index(NEW):b.index("  store(receipt,{'status':'PRIVATE_SENT_CONFIRMED'",b.index(NEW))]+a[end:]
 expected=expected.replace("   'media_type':item_kind,'media_bytes':media_bytes,\n", "   'media_type':item_kind,'media_bytes':media_bytes,\n   'telegram_photo_file_id':photo_id,\n",1)
 if expected!=b:stop('STAGED_HAS_OTHER_CHANGES')
 return old,new,False
def install():
 old,new,done=preflight()
 if done:return report(status='SENDER_PHOTO_ID_ALREADY_INSTALLED',telegram_calls=0,publications=0)
 test=subprocess.run(['/usr/bin/python3',str(STAGED),'selftest'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=15)
 if test.returncode or 'SELFTEST_PASS' not in test.stdout:stop('SENDER_SELFTEST_FAILED')
 digest=hashlib.sha256(old).hexdigest()[:16]
 backup=O/('news_rg_sender_before_photo_id_'+digest+'.py')
 if backup.exists() or backup.is_symlink():stop('BACKUP_EXISTS_STOP')
 fd=os.open(str(backup),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'wb') as f:f.write(old);f.flush();os.fsync(f.fileno())
 mode=stat.S_IMODE(LIVE.stat().st_mode)
 if read(LIVE)!=old:stop('CONCURRENT_SOURCE_CHANGE')
 try:
  put(LIVE,new,mode)
  run=subprocess.run(['/usr/bin/python3',str(LIVE),'selftest'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=15)
  if run.returncode or 'SELFTEST_PASS' not in run.stdout:stop('POSTINSTALL_SELFTEST_FAILED')
 except Exception:
  put(LIVE,old,mode)
  raise
 report(status='SENDER_PHOTO_ID_FIX_INSTALLED',backup=str(backup),telegram_calls=0,publications=0,pollers=0)
def recover():
 receipt=O/'news_rg_private_multipart_receipts_v1'/(KEY+'.json')
 decision=O/'news_rg_editorial_decisions_v1'/(KEY+'.json')
 stage=O/'news_rg_private_review_staging'/(KEY+'.json')
 r=json.loads(read(receipt,20000));d=json.loads(read(decision,20000));s=json.loads(read(stage,20000))
 if not(r.get('status')=='PRIVATE_SENT_CONFIRMED' and r.get('draft_id')==KEY and r.get('message_id')==MESSAGE and r.get('public_publication')=='OFF'):stop('RECEIPT_NOT_VERIFIED')
 if not(d.get('decision')=='editorially_accepted_not_published' and d.get('draft_id')==KEY and d.get('telegram_message_id')==MESSAGE and d.get('public_publication')=='OFF'):stop('DECISION_NOT_VERIFIED')
 if not(s.get('draft_id')==KEY and s.get('editorial_status')=='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED' and s.get('public_publication')=='OFF'):stop('STAGING_NOT_VERIFIED')
 if r.get('telegram_photo_file_id'):return report(status='PHOTO_ID_ALREADY_PRESENT',publications=0)
 found=set();archives=[]
 for p in O.glob('updates_handoff_guarded_*.json'):
  if p.is_symlink() or not p.is_file() or p.stat().st_size>2000000:continue
  try: updates=json.loads(p.read_text('utf8')).get('updates',[])
  except (ValueError,OSError):continue
  for u in updates:
   q=u.get('callback_query') or {}
   if q.get('data')!='ne1:accept:'+KEY:continue
   msg=q.get('message') or {}
   if msg.get('message_id')!=MESSAGE:continue
   photos=msg.get('photo') or []
   if isinstance(photos,list) and photos and isinstance(photos[-1],dict):
    fid=photos[-1].get('file_id')
    if isinstance(fid,str) and re.fullmatch(r'[A-Za-z0-9_-]{15,255}',fid):
     found.add(fid);archives.append(p.name)
 if len(found)!=1:return report(status='HISTORIC_PHOTO_ID_NOT_PROVABLE',matching_ids=len(found),telegram_calls=0,publications=0,manual_redispatch=False)
 # Archive proof only: never synthesize an ID or request Telegram forwarding.
 fid=next(iter(found))
 if read(receipt,20000)!=json.dumps(r,ensure_ascii=False).encode('utf8'):
  # Preserve original formatting while verifying semantic stability by re-reading.
  if json.loads(read(receipt,20000))!=r:stop('RECEIPT_CHANGED')
 else:pass
 r['telegram_photo_file_id']=fid
 put(receipt,json.dumps(r,ensure_ascii=False,sort_keys=True).encode('utf8'),stat.S_IMODE(receipt.stat().st_mode))
 report(status='HISTORIC_PHOTO_ID_RECOVERED_FROM_CALLBACK',archive=archives[0],telegram_calls=0,publications=0)
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:
   assert re.fullmatch(r'[A-Za-z0-9_-]{15,255}','A'*30)
   print('NEWS_RG_PHOTO_RECEIPT_FIX_SELFTEST_PASS')
  elif mode==['preflight']:
   _,_,done=preflight();report(status='ALREADY_INSTALLED' if done else 'PREFLIGHT_PASS',telegram_calls=0)
  elif mode==['install']:install()
  elif mode==['recover-8073']:recover()
  else:stop('EXPECTED_MODE')
 except Exception as e:
  report(status='SAFE_STOP',reason=str(e)[:130],telegram_calls=0,publications=0);sys.exit(2)
