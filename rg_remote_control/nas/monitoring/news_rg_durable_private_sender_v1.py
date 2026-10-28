#!/usr/bin/env python3
"""NEWS RG: one private editorial photo pilot. No polling or public publishing."""
import os,sys,json,time,pathlib,uuid,urllib.request,urllib.error,urllib.parse,hashlib
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
sys.path.insert(0,str(O))
import news_rg_multipart as media_support
import news_rg_wrong_photo_supersession_v1 as supersession
OUT=O/'news_rg_private_multipart_receipts_v1'
ST=O/'news_rg_private_review_staging'
def die(why):raise RuntimeError(why)
def output(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True))
def eligible():
 blocked=set()
 v1=O/'news_rg_private_pilot_claim_v1.json'
 if v1.is_file():blocked.add(json.loads(v1.read_text()).get('draft_id'))
 for directory in (O/'news_rg_private_delivery_v2',OUT):
  if directory.is_dir():blocked.update(p.stem for p in directory.glob('*.json'))
 for p in sorted(ST.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
  if not p.is_file() or p.is_symlink() or p.stat().st_size>16000:continue
  item=json.loads(p.read_text())
  key=item.get('draft_id')
  if not isinstance(key,str) or len(key)!=24 or any(c not in '0123456789abcdef' for c in key):continue
  if key in blocked:continue
  if item.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1':continue
  if item.get('telegram_delivery')!='NOT_SENT' or item.get('public_publication')!='OFF':continue
  if item.get('editorial_status') not in ('HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED'):continue
  text=str(item.get('proposed_text',''))
  if not 60<=len(text)<=900 or 'НЕВДАЛО' in text.upper() or any(c in text for c in 'ыъэёЫЪЭЁ'):continue
  if 'INSIDER UA | Прислати контент' in text:continue
  return item
 die('NO_NEW_ELIGIBLE_DRAFT')
def store(p,content):
 tmp=p.with_suffix('.tmp')
 try:
  with open(tmp,'w',encoding='utf-8') as f:
   os.chmod(tmp,0o600);json.dump(content,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if tmp.exists():tmp.unlink()
def pack(photo,mime,caption,chat,key):
 boundary='RGNEWS'+uuid.uuid4().hex
 suffix={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[mime]
 original=media_support.build(photo,'review.'+suffix,mime,caption,chat,boundary)
 ending=('\r\n--'+boundary+'--\r\n').encode()
 if not original.endswith(ending):die('MULTIPART_BOUNDARY_INVALID')
 buttons={'inline_keyboard':[[{'text':'✅ Схвалити (без публікації)','callback_data':'ne1:accept:'+key},
                              {'text':'❌ Відхилити','callback_data':'ne1:reject:'+key}]]}
 field=('\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="reply_markup"\r\n\r\n').encode()
 body=original[:-len(ending)]+field+json.dumps(buttons,ensure_ascii=False).encode()+ending
 return body,boundary
MAX_VIDEO_BYTES=45*1024*1024
VIDEO_HOSTS={'cdn1.telesco.pe','cdn2.telesco.pe','cdn3.telesco.pe',
             'cdn4.telesco.pe','cdn5.telesco.pe'}
def video_source_allowed(url):
 if not isinstance(url,str) or len(url)>3500:return False
 try:
  u=urllib.parse.urlsplit(url)
  return (u.scheme=='https' and u.hostname in VIDEO_HOSTS and
          not u.username and not u.password and u.port in (None,443))
 except ValueError:return False
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise RuntimeError('VIDEO_SOURCE_REDIRECT_REFUSED')
def load_original_video(url):
 if not video_source_allowed(url):die('VIDEO_ORIGIN_NOT_APPROVED')
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0',
   'Referer':'https://t.me/','Accept':'video/mp4,video/*'})
 opener=urllib.request.build_opener(NoRedirect())
 try:
  with opener.open(req,timeout=22) as resp:
   length=int(resp.headers.get('Content-Length','0') or 0)
   if length>MAX_VIDEO_BYTES:die('VIDEO_TOO_BIG_45MB_LIMIT')
   typ=resp.headers.get('Content-Type','').split(';')[0].strip().lower()
   if typ not in ('video/mp4','application/octet-stream','binary/octet-stream'):
    die('VIDEO_MIME_NOT_MP4')
   raw=resp.read(MAX_VIDEO_BYTES+1)
 except urllib.error.HTTPError as e:die('VIDEO_ORIGIN_HTTP_'+str(e.code))
 if len(raw)>MAX_VIDEO_BYTES or len(raw)<256:die('VIDEO_SIZE_INVALID')
 # MP4 ISO BMFF box ftyp magic at byte offset 4, not a JPEG proxy.
 if raw[4:8]!=b'ftyp':die('VIDEO_MAGIC_NOT_MP4')
 return raw,'video/mp4'
def pack_original_video(video,caption,chat,key):
 boundary='RGVIDEO'+uuid.uuid4().hex
 buttons={'inline_keyboard':[[{'text':'✅ Схвалити → Watermark RG','callback_data':'ne1:accept:'+key},
                              {'text':'❌ Відхилити','callback_data':'ne1:reject:'+key}]]}
 parts=[]
 for field,value in (('chat_id',str(chat)),('caption',caption),
    ('supports_streaming','true'),('reply_markup',json.dumps(buttons,ensure_ascii=False))):
  parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+field+
   '"\r\n\r\n'+value+'\r\n').encode('utf8'))
 parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="video"; filename="review.mp4"\r\n'
   'Content-Type: video/mp4\r\n\r\n').encode('ascii')+video+b'\r\n')
 parts.append(('--'+boundary+'--\r\n').encode('ascii'))
 return b''.join(parts),boundary
def run(mode):
 if os.geteuid()!=0:die('SUDO_REQUIRED')
 worker=O/'rg_news2_p31_guarded_callback_once.py'
 if not worker.is_file() or worker.is_symlink() or '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in worker.read_text():die('EDITORIAL_WORKER_ROUTE_UNVERIFIED')
 moderation=B/'rg_moderation.py'
 hook=O/'news_rg_editorial_callbacks_v1.py'
 if moderation.is_symlink() or hook.is_symlink() or not hook.is_file():die('EDITORIAL_CALLBACK_NOT_INSTALLED')
 if '# NEWS_RG_EDITORIAL_HOOK_V1' not in moderation.read_text():die('EDITORIAL_HOOK_NOT_INSTALLED')
 if OUT.is_symlink():die('RECEIPT_DIR_UNSAFE')
 # Halt after uncertain sends and allow at most ONE outstanding editorial card.
 if OUT.is_dir():
  for p in OUT.glob('*.json'):
   if p.is_symlink() or p.stat().st_size>20000:die('UNSAFE_PREVIOUS_RECEIPT')
   if supersession.is_superseded(p):continue
   data=json.loads(p.read_text())
   status=data.get('status')
   if status in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY'):
    die('PAUSED_UNCERTAIN_DELIVERY_REQUIRES_REVIEW')
   if status=='PRIVATE_SENT_CONFIRMED':
    decision=O/'news_rg_editorial_decisions_v1'/(p.stem+'.json')
    if not decision.is_file() or decision.is_symlink():die('WAITING_FOR_EDITORIAL_DECISION')
    val=json.loads(decision.read_text())
    if val.get('telegram_message_id')!=data.get('message_id') or val.get('draft_id')!=p.stem or val.get('decision') not in ('editorially_accepted_not_published','editorially_rejected') or val.get('public_publication')!='OFF':die('INVALID_PREVIOUS_EDITORIAL_DECISION')
 item=eligible()
 chat=media_support.identity()
 item_kind=item.get('media_type','photo')
 if item_kind not in ('video','photo'):die('UNSUPPORTED_STAGED_MEDIA_TYPE')
 if item_kind=='video':
  if item.get('watermark_required') is not True:die('VIDEO_WATERMARK_REQUIRED')
  original_url=item.get('original_video_url')
  video,mime=load_original_video(original_url)
  media_bytes=len(video)
 else:
  if item.get('original_video_url') or item.get('watermark_required'):
   die('VIDEO_AS_PHOTO_REFUSED')
  photo,mime=media_support.media(item['media_url'])
  media_bytes=len(photo)
 text=item['proposed_text']
 caption=('⚠️ NEWS RG · ПРИВАТНА ПЕРЕВІРКА. НЕ ПУБЛІКУВАТИ.\n'
          +('ОРИГІНАЛЬНЕ ВІДЕО. Після схвалення → Watermark RG.\n\n' if item_kind=='video'
            else 'Факти та фото потребують перевірки.\n\n')+text)[:1000]
 if item_kind=='video':
  body,boundary=pack_original_video(video,caption,chat,item['draft_id'])
 else:
  body,boundary=pack(photo,mime,caption,chat,item['draft_id'])
 if mode=='preflight':
  return {'status':'PRIVATE_ONE_CARD_READY','draft_id':item['draft_id'],
    'media_type':item_kind,'media_mime':mime,'media_bytes':media_bytes,
    'watermark_required':item_kind=='video','buttons':['accept','reject'],
    'delivery_claims':0,'telegram_sends':0,'publications':0}
 # Validate credentials BEFORE creating the at-most-once delivery claim.
 bot_token=media_support.token()
 OUT.mkdir(mode=0o700,exist_ok=True)
 os.chmod(OUT,0o700)
 receipt=OUT/(item['draft_id']+'.json')
 fd=os.open(str(receipt),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:
  json.dump({'status':'SENDING_UNCERTAIN','draft_id':item['draft_id'],'created_at':int(time.time())},f)
  f.flush();os.fsync(f.fileno())
 # Credential is retrieved locally from the existing private transport helper.
 url='https://api.telegram.org/bot'+bot_token+('/sendVideo' if item_kind=='video' else '/sendPhoto')
 req=urllib.request.Request(url,data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
 try:
  with urllib.request.urlopen(req,timeout=40) as result:
   response=json.loads(result.read(100000))
  message=response.get('result') if response.get('ok') is True else None
  if not isinstance(message,dict) or not isinstance(message.get('message_id'),int):die('ACK_MISSING')
  dest=message.get('chat') or {}
  if int(dest.get('id',0))!=chat or dest.get('type')!='private':die('ACK_WRONG_CHAT')
  if item_kind=='video' and not ((message.get('video') or {}).get('file_id')):
   die('VIDEO_ACK_MISSING_FILE_ID')
  if item_kind=='photo' and not message.get('photo'):
   die('PHOTO_ACK_MISSING')
  store(receipt,{'status':'PRIVATE_SENT_CONFIRMED','draft_id':item['draft_id'],
   'message_id':message['message_id'],'confirmed_at':int(time.time()),'public_publication':'OFF',
   'media_type':item_kind,'media_bytes':media_bytes,
   'original_video_file_id':(message.get('video') or {}).get('file_id') if item_kind=='video' else None})
  return {'status':'PRIVATE_SENT_CONFIRMED','draft_id':item['draft_id'],
    'message_id':message['message_id'],'buttons':['accept','reject'],'publications':0}
 except urllib.error.HTTPError as e:
  store(receipt,{'status':'HTTP_REJECTED_NO_RETRY','draft_id':item['draft_id'],
    'http_status':e.code,'attempted_at':int(time.time()),'public_publication':'OFF'})
  die('HTTP_REJECTED_NO_RETRY_'+str(e.code))
 except Exception as e:
  reason=str(e) if str(e) in ('ACK_MISSING','ACK_WRONG_CHAT') else type(e).__name__
  store(receipt,{'status':'UNCERTAIN_NO_RETRY','draft_id':item['draft_id'],
    'error_class':reason,'attempted_at':int(time.time()),'public_publication':'OFF'})
  die('UNCERTAIN_NO_RETRY_'+reason)
def selftest():
 photo=b'\xff\xd8\xfftest'
 data,bound=pack(photo,'image/jpeg','Тест',123,'a'*24)
 assert b'name="reply_markup"' in data and b'ne1:reject:' in data
 assert data.endswith(('--'+bound+'--\r\n').encode())
 video=b'\x00\x00\x00\x18ftypisom'+b'test_video'
 raw,bound2=pack_original_video(video,'Оригінальне відео',123,'b'*24)
 assert b'name="video"' in raw and b'filename="review.mp4"' in raw
 assert b'ne1:accept:' in raw and b'Watermark RG' in raw
 assert raw.endswith(('--'+bound2+'--\r\n').encode())
 assert video_source_allowed('https://cdn4.telesco.pe/file/original.mp4')
 assert not video_source_allowed('https://evil.example/video.mp4')
 print('NEWS_RG_DURABLE_PRIVATE_MULTIPART_SELFTEST_PASS')
if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args in (['preflight'],['send-one']):output(**run(args[0]))
  else:die('BAD_MODE')
 except Exception as e:
  reason=str(e)
  if 'https' in reason or 'bot' in reason.lower():reason=type(e).__name__
  output(status='SAFE_STOP',reason=reason[:110],publications=0)
  sys.exit(2)
