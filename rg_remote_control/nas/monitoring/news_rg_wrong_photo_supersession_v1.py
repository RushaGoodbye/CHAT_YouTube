#!/usr/bin/env python3
"""Supersede one demonstrably incorrect manual photo preview with its video.
No fake moderator decision, no publishing, no Telegram calls, no pollers.
Only the exact nexta_live/125698 photo->video migration is supported.
"""
import os,sys,json,hashlib,pathlib,time,fcntl
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
ST=O/'news_rg_private_review_staging'
R=O/'news_rg_private_multipart_receipts_v1'
D=O/'news_rg_editorial_decisions_v1'
LEDGER=O/'news_rg_wrong_photo_supersession_v1'
URL='https://t.me/nexta_live/125698'
OLD=hashlib.sha256(('NEWS_RG_MANUAL_LINK_V1\0'+URL).encode()).hexdigest()[:24]
NEW=hashlib.sha256(('NEWS_RG_MANUAL_VIDEO_V2\0'+URL).encode()).hexdigest()[:24]
SCHEMA='NEWS_RG_WRONG_PHOTO_SUPERSEDED_BY_VIDEO_V1'
LOCK=O/'news_rg_private_dispatch.lock'
def fail(reason):raise RuntimeError(reason)
def read(p):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:fail('UNSAFE_OR_MISSING_'+p.name)
 try:return json.loads(p.read_text('utf8'))
 except (ValueError,UnicodeError,OSError):fail('INVALID_RECORD_'+p.name)
def inputs():
 old=read(ST/(OLD+'.json'))
 new=read(ST/(NEW+'.json'))
 rec=read(R/(OLD+'.json'))
 if old.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or old.get('draft_id')!=OLD or old.get('original_media_source')!=URL:
  fail('OLD_PHOTO_SOURCE_NOT_PROVEN')
 if old.get('media_type','photo')!='photo' or old.get('original_video_url'):
  fail('OLD_CARD_NOT_PHOTO')
 if old.get('public_publication')!='OFF' or old.get('telegram_delivery')!='NOT_SENT':
  fail('OLD_STAGING_NOT_SAFE')
 if new.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or new.get('draft_id')!=NEW or new.get('original_media_source')!=URL:
  fail('REPLACEMENT_SOURCE_NOT_PROVEN')
 if new.get('media_type')!='video' or new.get('watermark_required') is not True or not new.get('original_video_url'):
  fail('NEW_CARD_NOT_ORIGINAL_VIDEO')
 if new.get('public_publication')!='OFF' or new.get('telegram_delivery')!='NOT_SENT':
  fail('NEW_VIDEO_STAGING_NOT_SAFE')
 if rec.get('status')!='PRIVATE_SENT_CONFIRMED' or rec.get('draft_id')!=OLD or rec.get('media_type') not in (None,'photo') or rec.get('public_publication')!='OFF':
  fail('OLD_PHOTO_RECEIPT_NOT_CONFIRMED')
 msg=rec.get('message_id')
 if type(msg)!=int or msg<=0:fail('OLD_PHOTO_MESSAGE_ID_INVALID')
 if (D/(OLD+'.json')).is_symlink():fail('OLD_DECISION_SYMLINK')
 if (D/(OLD+'.json')).exists():fail('OLD_CARD_ALREADY_DECIDED')
 return msg
def outstanding_exactly_old():
 if not R.is_dir() or R.is_symlink():fail('RECEIPTS_UNSAFE')
 unmatched=[]
 for p in R.glob('*.json'):
  d=read(p)
  if d.get('status') in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY'):
   fail('UNCERTAIN_OTHER_DELIVERY')
  if d.get('status')=='PRIVATE_SENT_CONFIRMED' and not (D/p.name).is_file():
   unmatched.append(p.stem)
 if unmatched!=[OLD]:fail('OUTSTANDING_NOT_EXACT_OLD_PHOTO_'+str(len(unmatched)))
def is_superseded(receipt_path):
 """Authoritative guard called by both dispatch and sender."""
 if receipt_path.name!=OLD+'.json':return False
 p=LEDGER/(OLD+'.json')
 if not p.exists():return False
 if LEDGER.is_symlink() or not LEDGER.is_dir():fail('SUPERSESSION_LEDGER_UNSAFE')
 marker=read(p)
 if (marker.get('schema')!=SCHEMA or marker.get('old_draft_id')!=OLD or
     marker.get('new_draft_id')!=NEW or marker.get('source_url')!=URL or
     marker.get('human_editorial_decision')!='NONE' or marker.get('public_publication')!='OFF'):
  fail('SUPERSESSION_MARKER_NOT_VALID')
 msg=inputs()
 if marker.get('old_message_id')!=msg:fail('SUPERSESSION_MESSAGE_MISMATCH')
 return True
def install_one():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if not LOCK.is_file() or LOCK.is_symlink():fail('EXISTING_DISPATCH_LOCK_MISSING')
 # This same lock is held by the existing dispatcher; no second sender.
 with LOCK.open('rb') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX)
  if LEDGER.is_symlink():fail('LEDGER_SYMLINK')
  if LEDGER.is_dir() and (LEDGER/(OLD+'.json')).is_file():
   if is_superseded(R/(OLD+'.json')):
    return {'status':'ALREADY_SUPERSEDED','old_photo_draft_id':OLD,'new_video_draft_id':NEW,'publications':0}
  msg=inputs()
  outstanding_exactly_old()
  LEDGER.mkdir(mode=0o700,exist_ok=True)
  os.chmod(LEDGER,0o700)
  target=LEDGER/(OLD+'.json')
  data={'schema':SCHEMA,'old_draft_id':OLD,'new_draft_id':NEW,
    'source_url':URL,'old_message_id':msg,
    'reason':'SOURCE_ORIGINAL_IS_VIDEO_WRONG_PHOTO_REVIEW_REPLACED',
    'human_editorial_decision':'NONE','public_publication':'OFF',
    'created_at':int(time.time()),'new_pollers':0}
  fd=os.open(str(target),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'w',encoding='utf8') as f:
   json.dump(data,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
  if not is_superseded(R/(OLD+'.json')):fail('POSTWRITE_SUPERSESSION_NOT_VALID')
  return {'status':'OLD_WRONG_PHOTO_SYSTEM_SUPERSEDED','old_photo_message_id':msg,
    'old_photo_draft_id':OLD,'new_video_draft_id':NEW,
    'human_decisions_fabricated':0,'new_pollers':0,'publications':0}
def preflight():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 msg=inputs()
 outstanding_exactly_old()
 return {'status':'WRONG_PHOTO_SAFE_SUPERSESSION_ELIGIBLE','old_message_id':msg,
   'old_photo_draft_id':OLD,'new_video_draft_id':NEW,'new_pollers':0,'publications':0}
def selftest():
 assert OLD=='3b246d51d3f347f04125fa23'
 assert NEW=='03b204953315fa3abf443b75'
 assert SCHEMA.endswith('_V1')
 # All operations below occur exclusively in temporary fixture directories.
 import tempfile
 global ST,R,D,LEDGER
 saved=ST,R,D,LEDGER
 try:
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp)
   ST=root/'st';R=root/'receipts';D=root/'decisions';LEDGER=root/'superseded'
   for p in (ST,R,D,LEDGER):p.mkdir()
   old={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1',
     'draft_id':OLD,'original_media_source':URL,'media_type':'photo',
     'public_publication':'OFF','telegram_delivery':'NOT_SENT'}
   new={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1',
     'draft_id':NEW,'original_media_source':URL,'media_type':'video',
     'watermark_required':True,'original_video_url':'https://cdn4.telesco.pe/file/test.mp4',
     'public_publication':'OFF','telegram_delivery':'NOT_SENT'}
   receipt={'status':'PRIVATE_SENT_CONFIRMED','draft_id':OLD,'message_id':123,
     'media_type':'photo','public_publication':'OFF'}
   for p,obj in ((ST/(OLD+'.json'),old),(ST/(NEW+'.json'),new),(R/(OLD+'.json'),receipt)):
    p.write_text(json.dumps(obj),encoding='utf8')
   assert inputs()==123
   outstanding_exactly_old()
   assert not is_superseded(R/(OLD+'.json'))
   marker={'schema':SCHEMA,'old_draft_id':OLD,'new_draft_id':NEW,
     'source_url':URL,'old_message_id':123,
     'human_editorial_decision':'NONE','public_publication':'OFF'}
   p=LEDGER/(OLD+'.json')
   p.write_text(json.dumps(marker),encoding='utf8')
   assert is_superseded(R/(OLD+'.json'))
   marker['old_message_id']=124
   p.write_text(json.dumps(marker),encoding='utf8')
   try:is_superseded(R/(OLD+'.json'))
   except RuntimeError as exc:assert str(exc)=='SUPERSESSION_MESSAGE_MISMATCH'
   else:raise AssertionError('INVALID_SUPERSESSION_ALLOWED')
   # A real click is never rewritten to a system override.
   (D/(OLD+'.json')).write_text('{"decision":"editorially_rejected"}',encoding='utf8')
   try:inputs()
   except RuntimeError as exc:assert str(exc)=='OLD_CARD_ALREADY_DECIDED'
   else:raise AssertionError('DECIDED_CARD_SUPERSEDED')
 finally:ST,R,D,LEDGER=saved
 print('NEWS_RG_WRONG_PHOTO_SUPERSESSION_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:print(json.dumps(preflight(),sort_keys=True))
  elif sys.argv[1:]==['supersede']:print(json.dumps(install_one(),sort_keys=True))
  else:fail('EXPECTED_SELFTEST_PREFLIGHT_SUPERSEDE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120] if isinstance(e,RuntimeError) else type(e).__name__,
   'telegram_bot_calls':0,'publications':0,'new_pollers':0}))
  sys.exit(2)
