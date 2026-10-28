#!/usr/bin/env python3
"""NEWS RG: one private editorial photo pilot. No polling or public publishing."""
import os,sys,json,time,pathlib,uuid,urllib.request,urllib.error,hashlib
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
sys.path.insert(0,'/tmp')
import news_rg_multipart as media_support
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
  if item.get('editorial_status')!='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED':continue
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
def run(mode):
 if os.geteuid()!=0:die('SUDO_REQUIRED')
 moderation=B/'rg_moderation.py'
 hook=O/'news_rg_editorial_callbacks_v1.py'
 if moderation.is_symlink() or hook.is_symlink() or not hook.is_file():die('EDITORIAL_CALLBACK_NOT_INSTALLED')
 if '# NEWS_RG_EDITORIAL_HOOK_V1' not in moderation.read_text():die('EDITORIAL_HOOK_NOT_INSTALLED')
 if OUT.is_symlink():die('RECEIPT_DIR_UNSAFE')
 if OUT.is_dir() and any(OUT.glob('*.json')):die('PRIVATE_PILOT_ALREADY_USED')
 item=eligible()
 chat=media_support.identity()
 photo,mime=media_support.media(item['media_url'])
 text=item['proposed_text']
 caption=('⚠️ NEWS RG · ПРИВАТНА ПЕРЕВІРКА. НЕ ПУБЛІКУВАТИ.\n'
          'Факти та фото потребують перевірки.\n\n'+text)[:1000]
 body,boundary=pack(photo,mime,caption,chat,item['draft_id'])
 if mode=='preflight':
  return {'status':'PRIVATE_ONE_CARD_READY','draft_id':item['draft_id'],
    'media_mime':mime,'media_bytes':len(photo),'buttons':['accept','reject'],
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
 url='https://api.telegram.org/bot'+bot_token+'/sendPhoto'
 req=urllib.request.Request(url,data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
 try:
  with urllib.request.urlopen(req,timeout=40) as result:
   response=json.loads(result.read(100000))
  message=response.get('result') if response.get('ok') is True else None
  if not isinstance(message,dict) or not isinstance(message.get('message_id'),int):die('ACK_MISSING')
  dest=message.get('chat') or {}
  if int(dest.get('id',0))!=chat or dest.get('type')!='private':die('ACK_WRONG_CHAT')
  store(receipt,{'status':'PRIVATE_SENT_CONFIRMED','draft_id':item['draft_id'],
   'message_id':message['message_id'],'confirmed_at':int(time.time()),'public_publication':'OFF'})
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
 print('NEWS_RG_PRIVATE_EDITORIAL_MULTIPART_SELFTEST_PASS')
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
