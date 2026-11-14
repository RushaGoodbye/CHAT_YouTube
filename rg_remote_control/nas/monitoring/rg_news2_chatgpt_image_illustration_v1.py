#!/usr/bin/env python3
"""NEWS2 optional GPT Image editorial illustration stage (NO public/private sends).

Generates ONE clearly attributed AI illustration for a legitimately eligible
TEXT-ONLY news draft, then safely promotes it to PHOTO moderation staging.
No attempt to invent document-photo evidence. Requires a root-owned secret key
file; without it, fails closed without billing or creating a claim.
Never runs Telegram, Cloudflare, callback handlers, or public publication.
"""
import base64,datetime,fcntl,hashlib,json,os,pathlib,re,stat,sys,tempfile,time,urllib.request,urllib.error

O=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
ST=O/'news_rg_private_review_staging'
OUT=O/'news_rg_private_multipart_receipts_v1'
CLAIMS=O/'news_rg_ai_illustration_v1'
SECRET=pathlib.Path('/volume1/docker/RG_SECRETS/rg_news_openai_image_api_key')
LOCK=O/'news_rg_ai_illustration_v1.lock'
MODEL='chatgpt-image-latest'
MAX_PER_DAY=3
MIN_SECONDS_BETWEEN=30*60
MAX_IMAGE_BYTES=9500000
class Halt(RuntimeError):pass
def sha(x):return hashlib.sha256(x).hexdigest()
def allowed_key():
 try:
  p=SECRET.lstat()
  if not stat.S_ISREG(p.st_mode) or p.st_uid!=0 or (p.st_mode&0o077)!=0 or p.st_size>300 or p.st_size<30:
   raise Halt('OPENAI_KEY_PERMISSIONS_OR_LENGTH_INVALID')
  key=SECRET.read_text().strip()
  if '\n' in key or not key.startswith('sk-'):raise Halt('OPENAI_KEY_FORMAT_INVALID')
  return key
 except FileNotFoundError:raise Halt('OPENAI_KEY_NOT_CONFIGURED')
def read(p,limit=24000):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:
  raise Halt('UNSAFE_DRAFT_OR_RECEIPT')
 return json.loads(p.read_text('utf8'))
def atomic(p,d):
 fd,tmp=tempfile.mkstemp(prefix='.ai_illustration_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),0o600);f.write(d);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def check_draft(path,now):
 v=read(path)
 key=path.stem
 if not re.fullmatch('[0-9a-f]{24}',key) or v.get('draft_id')!=key:return None
 if v.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1':return None
 if v.get('media_type')!='text' or v.get('editorial_status')!='HUMAN_FACT_AND_TEXT_REVIEW_REQUIRED':
  return None
 if v.get('telegram_delivery')!='NOT_SENT' or v.get('public_publication')!='OFF':return None
 if v.get('original_video_reference_unavailable') or v.get('original_video_url') or v.get('watermark_required'):return None
 if (OUT/(key+'.json')).exists() or (CLAIMS/(key+'.json')).exists():return None
 if v.get('manual_submission') is not True:
  if (v.get('ai_editorial_review') or {}).get('approved') is not True:return None
  try:
   if int(v.get('editorial_importance') or 0)<55:return None
  except (TypeError,ValueError):return None
 try:timestamp=int(v.get('posted_at',0))
 except (TypeError,ValueError):return None
 if not 0<=now-timestamp<=8*3600:return None
 text=v.get('proposed_text')
 if not isinstance(text,str) or not 60<=len(text)<=820 or any(x in text for x in 'ыъэёЫЪЭЁ'):
  return None
 return v
def eligible(now=None):
 now=int(now or time.time())
 if ST.is_symlink() or CLAIMS.is_symlink():raise Halt('STAGING_DIRECTORY_UNSAFE')
 recent=[]
 for p in ST.glob('*.json'):
  try:
   d=check_draft(p,now)
   if d:recent.append((int(d.get('editorial_importance') or 0),d.get('posted_at') or 0,p,d))
  except (ValueError,OSError,TypeError,Halt):continue
 recent.sort(key=lambda x:(x[0],x[1]),reverse=True)
 return recent[0] if recent else None
def prompt(text):
 # Symbolic images, never fabricated "news photography" or identifiable people.
 stripped=' '.join(text.split())[:750]
 return ('Create a horizontal 3:2 editorial ILLUSTRATION for a Ukrainian news '
         'moderation card, not a photograph or documentary record. '
         'Modern high-quality illustrated magazine aesthetic, clear focal point, '
         'restrained colours, accurate broad subject symbolism, no fabricated '
         'identifiable people or document screenshots. No flags if uncertain, '
         'no readable words, no logos, no watermarks. Never imply this scene '
         'was photographed. Topic to illustrate symbolically: '+stripped)
def generate(key,topic,token):
 request={'model':MODEL,'prompt':prompt(topic),'size':'1536x1024',
  'quality':'medium','output_format':'jpeg','output_compression':80,'n':1}
 req=urllib.request.Request('https://api.openai.com/v1/images/generations',
   data=json.dumps(request,ensure_ascii=False).encode('utf8'),
   headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
            'User-Agent':'RGNEWS2-AI-Illustration/1.0'},method='POST')
 with urllib.request.urlopen(req,timeout=115) as res:
  data=res.read(18000000)
 response=json.loads(data)
 parts=response.get('data') or []
 if len(parts)!=1 or not isinstance(parts[0].get('b64_json'),str):
  raise Halt('IMAGE_API_RESPONSE_INVALID')
 raw=base64.b64decode(parts[0]['b64_json'],validate=True)
 if not 2048<=len(raw)<=MAX_IMAGE_BYTES or not raw.startswith(b'\xff\xd8\xff'):
  raise Halt('GENERATED_JPEG_UNVERIFIED')
 return raw
def today_claims(now):
 day=datetime.datetime.fromtimestamp(now,datetime.timezone.utc).date().isoformat()
 today=0;last=0
 if not CLAIMS.is_dir():return 0,0
 for path in CLAIMS.glob('*.json'):
  try:
   v=read(path)
   created=int(v.get('claimed_at') or 0)
   if datetime.datetime.fromtimestamp(created,datetime.timezone.utc).date().isoformat()==day:
    today+=1
   last=max(last,created)
  except (OSError,ValueError,TypeError,Halt,OverflowError):continue
 return today,last
def tick(now=None):
 if os.geteuid()!=0:raise Halt('ROOT_REQUIRED')
 now=int(now or time.time())
 tk=allowed_key()   # Key must be present BEFORE claiming or making API requests.
 if ST.is_symlink() or OUT.is_symlink() or CLAIMS.is_symlink():
  raise Halt('UNSAFE_DIRECTORY_SYMLINK')
 CLAIMS.mkdir(mode=0o700,exist_ok=True)
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'status':'ALREADY_RUNNING','generated':0}
  count,last=today_claims(now)
  if count>=MAX_PER_DAY:return {'status':'DAILY_IMAGE_CAP','generated':0}
  if now-last<MIN_SECONDS_BETWEEN:return {'status':'IMAGE_COOLDOWN','generated':0}
  row=eligible(now)
  if row is None:return {'status':'NO_ELIGIBLE_TEXT_DRAFTS','generated':0}
  _,_,path,record=row
  key=path.stem
  claim=CLAIMS/(key+'.json')
  flag=os.open(str(claim),os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(flag,'w',encoding='utf8') as f:
   json.dump({'draft_id':key,'claimed_at':now,'status':'GENERATION_UNCERTAIN_NO_AUTO_RETRY',
              'model':MODEL},f)
   f.flush();os.fsync(f.fileno())
  try:
   pic=generate(key,record['proposed_text'],tk)
   from news_rg_local_photo_cache_v1 import store
   digest=store(key,pic,'image/jpeg')
   original=read(path)
   if original!=record:raise Halt('DRAFT_CHANGED_WHILE_GENERATING')
   converted=dict(record)
   prefix='🎨 Ілюстрація ШІ. Зображення не є документальним фото події.\n\n'
   if len(prefix+record['proposed_text'])>900:raise Halt('CAPTION_TOO_LONG_FOR_AI_DISCLAIMER')
   converted.update({'media_type':'photo','editorial_status':'HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED',
    'local_media_sha256':digest,'local_media_mime':'image/jpeg',
    'visual_origin':'AI_GENERATED_ILLUSTRATION','visual_model':MODEL,
    'media_url':'','proposed_text':prefix+record['proposed_text'],
    'ai_visual_generated_at':now})
   atomic(path,(json.dumps(converted,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
   atomic(claim,(json.dumps({'draft_id':key,'claimed_at':now,'status':'AI_ILLUSTRATION_STAGED',
     'sha256':digest,'model':MODEL,'telegram_calls':0,'publications':0},
     sort_keys=True)+'\n').encode())
   return {'status':'AI_ILLUSTRATION_STAGED','draft_id':key,'media_type':'photo',
           'ai_visual_disclosed':True,'generated':1,'telegram_calls':0,'publications':0}
  except Exception as e:
   # Generation may have been billed, but was never published or privately sent.
   # Fail closed; no retry or pretending to have a source photograph.
   atomic(claim,(json.dumps({'draft_id':key,'claimed_at':now,
     'status':'GENERATION_UNCERTAIN_NO_AUTO_RETRY','error_class':type(e).__name__,
     'model':MODEL},sort_keys=True)+'\n').encode())
   raise
 finally:os.close(fd)
def selftest():
 assert MODEL=='chatgpt-image-latest'
 assert 'not a photograph' in prompt('Невідома новина')
 assert 'no readable words' in prompt('Невідома новина')
 assert len('a'*24)==24 and MAX_PER_DAY<=3
 print('NEWS2_GPT_IMAGE_ILLUSTRATION_SELFTEST_PASS')
if __name__=='__main__':
 try:
  mode=sys.argv[1:]
  if mode==['selftest']:selftest()
  elif mode==['status']:
   print(json.dumps({'status':'API_KEY_CONFIGURED' if SECRET.is_file() and not SECRET.is_symlink() else 'OPENAI_KEY_NOT_CONFIGURED',
     'daily_cap':MAX_PER_DAY,'model':MODEL,'telegram_calls':0,'publications':0}))
  elif mode==['tick']:
   print(json.dumps(tick(),ensure_ascii=False,sort_keys=True))
  else:raise Halt('UNSUPPORTED_MODE')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120] if isinstance(e,Halt) else type(e).__name__,
   'telegram_calls':0,'publications':0}))
  raise SystemExit(2)
