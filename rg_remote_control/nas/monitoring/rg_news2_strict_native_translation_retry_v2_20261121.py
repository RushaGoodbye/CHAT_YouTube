#!/usr/bin/env python3
"""NEWS2 recover native pending videos: strict quotation-free Gemini retries.
One-shot, idempotent, bounded (3 pending, max 3 model requests per record).
Use only existing pinned stage_native_video_file and private dispatcher.
No public API sends, no new poller, no module/manifest changes.
"""
import datetime as dt,fcntl,hashlib,json,os,pathlib,re,sys,time,traceback
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
P=O/'news_rg_native_video_translation_pending_v1'
ST=O/'news_rg_private_review_staging'
RECEIPTS=O/'news_rg_publication_receipts_v1'
sys.path[:0]=[str(O),str(B)]
def emit(**obj):print(json.dumps(obj,ensure_ascii=False,indent=2),flush=True)
def require(ok,code):
 if not ok:raise RuntimeError(code)
def load(p,limit=30000):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
 try:
  d=json.loads(p.read_text('utf8'))
  return d if isinstance(d,dict) else None
 except Exception:return None
def protected_source(d):
 return d.get('original_text','')
def validate_pending(p,d):
 require(d.get('schema')=='RG_NATIVE_VIDEO_PENDING_UKRAINIAN_V1','BAD_PENDING_SCHEMA')
 require(d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT','ALREADY_RESOLVED')
 require(d.get('editorial_status')=='TRANSLATION_REQUIRED_BEFORE_MODERATION','EDITORIAL_STATUS_CHANGED')
 require(d.get('public_publication')=='OFF' and d.get('auto_publish_allowed') is False,'PUBLIC_GATE_CHANGED')
 require(d.get('telegram_delivery')=='NOT_SENT','ALREADY_DELIVERED')
 require(d.get('video_file_id_only') is True and d.get('video_bytes_downloaded') is False,'VIDEO_BYTES_CONTRACT_CHANGED')
 require(d.get('media_type')=='video','NOT_NATIVE_VIDEO')
 fid=d.get('original_video_file_id');unique=d.get('original_video_file_unique_id')
 require(isinstance(fid,str) and re.fullmatch(r'[A-Za-z0-9_-]{15,255}',fid),'BAD_FILE_ID')
 require(isinstance(unique,str) and 8<=len(unique)<=255,'BAD_FILE_UNIQUE_ID')
 require(type(d.get('original_video_file_size'))==int and 0<d['original_video_file_size']<=2_000_000_000,'BAD_SIZE')
 require(type(d.get('source_message_id'))==int and d['source_message_id']>0,'BAD_MESSAGE_ID')
 require(type(d.get('source_timestamp'))==int and d['source_timestamp']>0,'BAD_MESSAGE_DATE')
 require(isinstance(d.get('original_text'),str) and 60<=len(d['original_text'])<=3500,'BAD_ORIGINAL')
 require(isinstance(d.get('original_media_source'),str) and 0<len(d['original_media_source'])<=500,'BAD_SOURCE')
 require(p.stem==d.get('pending_id'),'PENDING_ID_MISMATCH')
def envelope(d):
 import rg_moderation
 cfg=rg_moderation.config()
 chat=cfg.get('moderation_chat_id')
 moderators=cfg.get('moderators') or []
 require(type(chat)==int and chat>0 and chat in [int(x) for x in moderators],'MODERATOR_CONFIG_CHANGED')
 msg={'message_id':d['source_message_id'],'date':d['source_timestamp'],
 'chat':{'id':chat,'type':'private'},'from':{'id':chat},
 'caption':d['original_text'],
 'video':{'file_id':d['original_video_file_id'],
    'file_unique_id':d['original_video_file_unique_id'],
    'file_size':d['original_video_file_size'],'mime_type':'video/mp4'}}
 src=d['original_media_source']
 match=re.fullmatch(r'https://t\.me/([A-Za-z0-9_]{5,32})/([1-9][0-9]*)',src)
 if match:msg['forward_origin']={'type':'channel','chat':{'username':match.group(1)},'message_id':int(match.group(2))}
 else:require(src=='telegram-private-video:'+str(d['source_message_id']),'NON_RECONSTRUCTABLE_SOURCE')
 group=d.get('media_group_id')
 if group:
  require(isinstance(group,str) and len(group)<128,'UNSAFE_GROUP')
  msg['media_group_id']=group
 return msg
def already_handled(d):
 uid=d['original_video_file_unique_id']
 # Scan private staging; matching video means the original is already in moderation.
 for p in ST.glob('*.json'):
  x=load(p)
  if not x:continue
  if x.get('original_video_file_unique_id')==uid or x.get('original_video_file_id')==d['original_video_file_id']:
   return 'STAGING_ALREADY_HAS_ORIGINAL_VIDEO'
 return None
def translate_strict(original,key,adapter,intake,max_attempts=3):
 causes=[]
 for i in range(max_attempts):
  # No direct quotes: guard NEW_UNSOURCED_QUOTE remains untouched.
  instructions=(
   'Ти перекладач редакції українських новин. Переклади російський оригінал українською. '
   'Виведи лише 200–600 символів українською мовою. '
   'СУВОРО ЗАБОРОНЕНО використовувати лапки будь-якого виду: « » “ ” „ " та прямі цитати. '
   'Якщо оригінал містить пряму мову, передай її непрямою мовою з посиланням на автора. '
   'Не додавай нових чисел, дат, імен, посад, причин, висновків чи жодних нових фактів. '
   'Не вигадуй джерела. Збережи суть, конкретику та застереження. '
   'Не додавай заголовків, закликів підписатися, промо чи коментарів. '
   'Не доповнюй оригінал і не цитуй інструкції всередині джерела. '
   +('Попередня відповідь порушила редакційні перевірки. Перефразуй лише перевірені факти без лапок. ' if i else '')
  )
  payload={'systemInstruction':{'parts':[{'text':instructions}]},
   'contents':[{'role':'user','parts':[{'text':original}]}],
   'generationConfig':{'temperature':0.0,'maxOutputTokens':1100}}
  try:
   raw=adapter.request(adapter.API+':generateContent',key,payload,35)
   candidates=raw.get('candidates') or []
   require(candidates and candidates[0].get('finishReason') in (None,'STOP'),'AI_NO_CANDIDATE')
   drafted=''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if isinstance(p,dict)).strip()
   if not drafted:raise RuntimeError('AI_EMPTY')
   # Extra quote lock: both literal quotes and adapted strict grounding guard.
   if any(ch in drafted for ch in ('«','»','“','”','„','"')):
    raise RuntimeError('QUOTATION_MARKS_RETURNED')
   code=adapter.verify(original,drafted)
   if code:raise RuntimeError('EDITORIAL_GUARD:'+str(code))
   if not intake.ukrainian_draft_ok(original,drafted):raise RuntimeError('INTAKE_EDITORIAL_GUARD')
   return drafted,causes
  except Exception as e:
   reason=str(e)
   if reason.startswith(('EDITORIAL_GUARD:','AI_','QUOTATION_MARKS_RETURNED','INTAKE_EDITORIAL_GUARD')):
    causes.append(reason[:90])
   else:
    causes.append('PROVIDER_ERROR_'+type(e).__name__)
   continue
 return None,causes
def run():
 require(os.geteuid()==0,'SUDO_REQUIRED')
 require(P.is_dir() and not P.is_symlink() and ST.is_dir() and not ST.is_symlink(),'UNSAFE_QUEUE')
 require(not (B/'PUBLISH_ENABLED').exists(),'PUBLICATION_GATE_NOT_OFF')
 import news_rg_gemini_35_adapter_v1 as adapter
 import news_rg_manual_link_intake_v1 as intake
 require(hasattr(intake,'stage_native_video_file'),'NO_NATIVE_INTAKE')
 require(hasattr(intake,'dispatch_once_async'),'NO_PRIVATE_DISPATCH')
 records=[]
 for p in P.glob('*.json'):
  d=load(p)
  if d and d.get('status')=='AWAITING_VERIFIED_UKRAINIAN_TEXT':
   records.append((p,d))
 records.sort(key=lambda a:a[0].stat().st_mtime,reverse=True)
 report={'status':'PRECHECK','pending_total':len(records),'model':adapter.MODEL,
 'telegram_calls':0,'publications':0,'new_pollers':0,'pinned_modules_changed':0}
 results=[]
 for p,d in records[:3]:
  item={'pending_id':p.stem}
  try:
   validate_pending(p,d)
   reason=already_handled(d)
   if reason:item['status']=reason
   else:
    msg=envelope(d)
    item['status']='ELIGIBLE_FOR_TRANSLATION'
  except Exception as e:item['status']='SAFE_SKIP';item['reason']=str(e)[:90]
  results.append(item)
 report['items']=results
 if '--apply' not in sys.argv:
  emit(**report);return
 require(adapter.credential() is not None,'GEMINI_CREDENTIAL_MISSING')
 lock=O/'news_rg_pending_translation_retry.lock'
 require(not lock.is_symlink(),'UNSAFE_LOCK')
 fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (OSError,BlockingIOError):raise RuntimeError('ANOTHER_TRANSLATION_RECOVERY_RUNNING')
  count=0
  for idx,(p,d) in enumerate(records[:3]):
   item=results[idx]
   if item['status']!='ELIGIBLE_FOR_TRANSLATION':continue
   # Only one new moderation card is attempted in this run, to prevent backlog burst.
   if count>=1:item['status']='HELD_FOR_NEXT_BATCH';continue
   if p.stem in set(os.environ.get('RG_TRANSLATION_SKIP_PENDING_IDS','').split(',')):
    item['status']='COOLDOWN_NO_AI'
    continue
   draft,causes=translate_strict(d['original_text'],adapter.credential(),adapter,intake)
   item['guard_failures']=causes
   item['gemini_attempts']=len(causes)+(1 if draft else 0)
   if not draft:
    item['status']='TRANSLATION_GUARDS_NOT_PASSED_OR_PROVIDER_UNAVAILABLE'
    continue
   msg=envelope(d)
   original_func=intake.prepare_ukrainian_with_status
   try:
    def verified_text(source):
     require(source==d['original_text'],'INTERNAL_SOURCE_CHANGED')
     return draft,'GEMINI_EDITED_REVIEW_REQUIRED','gemini-3.5-flash-lite-strict'
    intake.prepare_ukrainian_with_status=verified_text
    staging=intake.stage_native_video_file(msg)
   finally:intake.prepare_ukrainian_with_status=original_func
   item['intake_status']=staging.get('status')
   item['draft_id']=staging.get('draft_id')
   if staging.get('status')=='MANUAL_LINK_STAGED':
    draft_id=staging.get('draft_id')
    require(isinstance(draft_id,str) and re.fullmatch(r'[0-9a-f]{24}',draft_id),'INVALID_DRAFT_ID')
    saved=load(ST/(draft_id+'.json'))
    require(saved and saved.get('media_type')=='video' and
     saved.get('original_video_file_id')==d['original_video_file_id'] and
     saved.get('original_video_file_size')==d['original_video_file_size'] and
     saved.get('public_publication')=='OFF' and
     saved.get('review_media')=='ORIGINAL_TELEGRAM_VIDEO_FILE_ID','STAGED_PROVENANCE_MISMATCH')
    count+=1
    item['status']='PRIVATE_STAGING_CONFIRMED'
    # Queue the existing singleton dispatch (not another getUpdates poller).
    try:
     queued=intake.dispatch_once_async()
     item['private_dispatch_requested']=bool(queued)
     item['private_delivery_confirmed']=False
    except Exception as e:
     item['private_dispatch_requested']=False
     item['private_dispatch_error_class']=type(e).__name__
   elif staging.get('status')=='MANUAL_LINK_ALREADY_QUEUED':
    item['status']='ALREADY_QUEUED_NO_RESEND'
   else:
    item['status']='STAGING_GUARD_REFUSED'
  report['status']='BATCH_COMPLETE'
  emit(**report)
 finally:
  fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
if __name__=='__main__':
 try:run()
 except Exception as e:
  emit(status='SAFE_STOP',reason=str(e)[:110] if str(e).startswith(('SUDO_REQUIRED','UNSAFE','PUBLICATION_','GEMINI_','NO_','ANOTHER_')) else type(e).__name__,publications=0,new_pollers=0)
  sys.exit(2)
