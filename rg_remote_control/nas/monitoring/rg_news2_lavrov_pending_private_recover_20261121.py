#!/usr/bin/env python3
"""NEWS2 recover recently held original Telegram videos via the EXISTING pinned intake.
No new poller or public calls. Only genuine Ukrainian drafts pass to private moderation.
Dry-run default. --apply attempts at most one fresh pending video, with existing dedup.
"""
import datetime as dt,hashlib,importlib,importlib.util,json,os,pathlib,re,sys,time
O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
Q=O/'news_rg_native_video_translation_pending_v1'
ST=O/'news_rg_private_review_staging'
MAX_AGE_SECONDS=7200
def show(**kv):print(json.dumps(kv,ensure_ascii=False,indent=2),flush=True)
def read(p):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>16000:return None
 try:
  d=json.loads(p.read_text('utf8'))
  return d if isinstance(d,dict) else None
 except (OSError,ValueError,UnicodeError):return None
def require(x,reason):
 if not x:raise RuntimeError(reason)
def safe_pending(p,d):
 require(d.get('schema')=='RG_NATIVE_VIDEO_PENDING_UKRAINIAN_V1','SCHEMA_CHANGED')
 require(d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT','NOT_AWAITING_TRANSLATION')
 require(d.get('editorial_status')=='TRANSLATION_REQUIRED_BEFORE_MODERATION','EDITORIAL_STATUS_CHANGED')
 require(d.get('public_publication')=='OFF' and d.get('auto_publish_allowed') is False,'PUBLIC_GATE_CHANGED')
 require(d.get('telegram_delivery')=='NOT_SENT','ALREADY_DELIVERED')
 require(d.get('video_file_id_only') is True and d.get('video_bytes_downloaded') is False,'VIDEO_PROVENANCE_CHANGED')
 require(re.fullmatch(r'[A-Za-z0-9_-]{15,255}',str(d.get('original_video_file_id') or '')) is not None,'FILE_ID_INVALID')
 require(re.fullmatch(r'[A-Za-z0-9_-]{8,255}',str(d.get('original_video_file_unique_id') or '')) is not None,'FILE_UNIQUE_ID_INVALID')
 require(type(d.get('original_video_file_size'))==int and 0<d['original_video_file_size']<=2_000_000_000,'VIDEO_SIZE_INVALID')
 require(type(d.get('source_message_id'))==int and d['source_message_id']>0,'SOURCE_MSG_INVALID')
 require(type(d.get('source_timestamp'))==int and d['source_timestamp']>0,'SOURCE_DATE_INVALID')
 require(isinstance(d.get('original_text'),str) and 60<=len(d['original_text'])<=3500,'SOURCE_TEXT_INVALID')
 require(isinstance(d.get('original_media_source'),str) and len(d['original_media_source'])<=500,'SOURCE_IDENTITY_INVALID')
 age=max(0,time.time()-p.stat().st_mtime)
 require(age<=MAX_AGE_SECONDS,'STALE_PENDING_REQUIRES_EDITOR')
 return age
def synthetic(d):
 src=d['original_media_source']
 msg={'message_id':d['source_message_id'],'date':d['source_timestamp'],
  'caption':d['original_text'],
  'video':{'file_id':d['original_video_file_id'],
    'file_unique_id':d['original_video_file_unique_id'],
    'file_size':d['original_video_file_size'],'mime_type':'video/mp4'}}
 match=re.fullmatch(r'https://t\.me/([A-Za-z0-9_]{5,32})/([1-9][0-9]*)',src)
 if match:
  msg['forward_origin']={'type':'channel','chat':{'username':match.group(1)},'message_id':int(match.group(2))}
 elif src!='telegram-private-video:'+str(d['source_message_id']):
  raise RuntimeError('SOURCE_REFERENCE_UNRECONSTRUCTABLE')
 if d.get('media_group_id'):
  require(isinstance(d['media_group_id'],str) and len(d['media_group_id'])<128,'MEDIA_GROUP_INVALID')
  msg['media_group_id']=d['media_group_id']
 return msg
def main():
 require(os.geteuid()==0,'SUDO_REQUIRED')
 require(Q.is_dir() and not Q.is_symlink() and ST.is_dir() and not ST.is_symlink(),'STAGING_UNSAFE')
 import fcntl
 lock=O/'news_rg_manual_link_intake_v1.lock'
 # Do not hijack the live intake lock. Module handles exclusive staging itself.
 import news_rg_manual_link_intake_v1 as intake
 require(hasattr(intake,'stage_native_video_file') and hasattr(intake,'dispatch_once_async'),'INTAKE_MODULE_CONTRACT_CHANGED')
 records=[]
 for p in Q.glob('*.json'):
  d=read(p)
  if d and d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT':
   records.append((p,d))
 records.sort(key=lambda entry:entry[0].stat().st_mtime,reverse=True)
 report={'status':'PRECHECK','pending_total':len(records),'operation':'single_fresh_pending_only',
  'telegram_calls':0,'publications':0,'new_pollers':0}
 eligible=[]
 for p,d in records:
  try:age=safe_pending(p,d);msg=synthetic(d)
  except Exception as exc:
   report.setdefault('skipped',[]).append({'pending_id':p.stem,'reason':str(exc)[:80]})
   continue
  if 'лавров' not in d['original_text'].lower():
   report.setdefault('skipped',[]).append({'pending_id':p.stem,'reason':'NOT_TARGETED_LAVROV'})
   continue
  eligible.append((p,d,msg,age))
 report['eligible_count']=len(eligible)
 if '--apply' not in sys.argv:
  show(**report);return
 require(len(eligible)==1,'NOT_EXACTLY_ONE_FRESH_LAVROV_PENDING')
 p,d,msg,age=eligible[0]
 # Let the pinned intake enforce all editorial/source/video constraints and
 # ensure it constructs the same staging/duplicate identities as normal callbacks.
 result=intake.stage_native_video_file(msg)
 status=result.get('status')
 report['pending_id']=p.stem;report['intake_status']=status
 report['draft_id']=result.get('draft_id')
 if status=='MANUAL_LINK_STAGED':
  draft=ST/(result['draft_id']+'.json')
  st=read(draft)
  require(st and st.get('media_type')=='video' and
    st.get('review_media')=='ORIGINAL_TELEGRAM_VIDEO_FILE_ID' and
    st.get('original_video_file_id')==d['original_video_file_id'] and
    st.get('original_video_file_size')==d['original_video_file_size'] and
    st.get('public_publication')=='OFF' and
    st.get('telegram_delivery')=='NOT_SENT','STAGED_RECORD_NOT_VALIDATED')
  # Existing dispatcher only; lock and delivery receipts are still enforced there.
  dispatch=intake.dispatch_once_async()
  report['status']='STAGED_FOR_PRIVATE_MODERATION'
  report['dispatch_triggered']=bool(dispatch)
  report['private_delivery_confirmed']=False
 elif status in ('MANUAL_LINK_ALREADY_QUEUED','MANUAL_LINK_PREVIOUSLY_PUBLISHED_NO_RETRY'):
  report['status']='ALREADY_HANDLED_NO_RESEND'
 else:
  report['status']='TRANSLATION_OR_EDITORIAL_GATE_NOT_PASSED'
 report['publications']=0
 show(**report)
if __name__=='__main__':
 try:main()
 except Exception as e:
  show(status='SAFE_STOP',reason=str(e)[:250],publications=0,new_pollers=0)
  sys.exit(2)
