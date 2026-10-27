#!/usr/bin/env python3
"""NEWS RG private media transport: non-sending selftest and safe preflight.
Direct multipart uploads avoid Telegram's remote fetch of external CDN photo URLs.
Do NOT resend previous uncertain drafts. Public publishing and polling unsupported.
"""
import os,sys,json,pathlib,urllib.parse,urllib.request,urllib.error,importlib.util,mimetypes,uuid
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
D=O/'news_rg_private_review_staging'
V1=O/'news_rg_private_pilot_claim_v1.json'
V2=O/'news_rg_private_delivery_v2'
def ensure(ok,why):
 if not ok:raise RuntimeError(why)
def build(body,filename,mime,caption,chat,boundary):
 ensure(mime in ('image/jpeg','image/png','image/webp'),'NOT_AN_IMAGE')
 ensure(len(body)<=10_000_000,'PHOTO_TOO_LARGE')
 parts=[
  ('chat_id',str(chat).encode()),
  ('caption',caption.encode('utf-8'))
 ]
 data=bytearray()
 for key,value in parts:
  data.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n').encode())
  data.extend(value+b'\r\n')
 data.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="photo"; filename="'+filename+'"\r\nContent-Type: '+mime+'\r\n\r\n').encode())
 data.extend(body)
 data.extend(('\r\n--'+boundary+'--\r\n').encode())
 return bytes(data)
def identity():
 if str(B) not in sys.path:sys.path.insert(0,str(B))
 spec=importlib.util.spec_from_file_location('_newsrg_prod_mod',str(B/'rg_moderation.py'))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 cfg=m.config()
 chat=cfg.get('moderation_chat_id')
 allow=cfg.get('moderators')
 ensure(str(chat).isdigit() and not isinstance(chat,bool) and int(chat)>0,'CHAT_INVALID')
 ensure(isinstance(allow,(list,tuple,set)) and int(chat) in {int(v) for v in allow},'CHAT_NOT_ALLOWLISTED')
 return int(chat)
def token():
 t=os.environ.get('RG_NEWS_MOD_BOT_TOKEN','')
 if not t:
  p=pathlib.Path('/volume1/docker/RG_SECRETS/rg_telegram_bot_token')
  ensure(p.is_file() and not p.is_symlink(),'TOKEN_FILE_UNAVAILABLE')
  t=p.read_text().strip()
 import re
 ensure(re.fullmatch(r'\d{5,16}:[A-Za-z0-9_-]{20,}',t) is not None,'TOKEN_FORMAT_BAD')
 return t
def media(url):
 p=urllib.parse.urlsplit(url)
 ensure(p.scheme=='https' and p.hostname in ('cdn1.telesco.pe','cdn2.telesco.pe','cdn3.telesco.pe','cdn4.telesco.pe','cdn5.telesco.pe'),'MEDIA_HOST_UNAPPROVED')
 # Bounded read; reject unsupported media before any Bot API send.
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=15) as res:
  ct=res.headers.get('Content-Type','').split(';')[0].lower().strip()
  ensure(ct in ('image/jpeg','image/png','image/webp'),'MEDIA_TYPE_'+ct.replace('/','_'))
  data=res.read(10_000_001)
 ensure(len(data)<=10_000_000 and len(data)>100,'MEDIA_SIZE')
 if ct=='image/jpeg':ensure(data.startswith(b'\xff\xd8\xff'),'JPEG_SIGNATURE_BAD')
 if ct=='image/png':ensure(data.startswith(b'\x89PNG\r\n\x1a\n'),'PNG_SIGNATURE_BAD')
 if ct=='image/webp':ensure(data[:4]==b'RIFF' and data[8:12]==b'WEBP','WEBP_SIGNATURE_BAD')
 return data,ct
def available():
 old=None
 if V1.is_file():old=json.loads(V1.read_text()).get('draft_id')
 used={p.stem for p in V2.glob('*.json')} if V2.is_dir() else set()
 for p in sorted(D.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
  if p.is_symlink():continue
  obj=json.loads(p.read_text())
  key=obj.get('draft_id','')
  if key==old or key in used:continue
  if obj.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or obj.get('telegram_delivery')!='NOT_SENT' or obj.get('public_publication')!='OFF':continue
  txt=str(obj.get('proposed_text',''))
  if not 60<=len(txt)<=900 or 'НЕВДАЛО' in txt.upper() or any(ch in txt for ch in 'ыъэёЫЪЭЁ'):continue
  return obj
 raise RuntimeError('NO_NEW_ELIGIBLE_DRAFT')
def check():
 ensure(os.geteuid()==0,'SUDO_REQUIRED')
 chat=identity()
 obj=available()
 data,ct=media(obj['media_url'])
 return {'status':'READY_MULTIPART_PRIVATE_ONLY','draft_id':obj['draft_id'],'media_type':ct,
  'media_bytes':len(data),'private_chat_masked':str(chat)[:2]+'***','telegram_sends':0,
  'telegram_poll_calls':0,'publications':0,'old_uncertain_claims_preserved':True}
def selftest():
 b=build(b'\xff\xd8\xffABC','x.jpg','image/jpeg','тест',123,'RGNEWSBOUNDARY')
 assert b'Content-Disposition: form-data; name="photo"; filename="x.jpg"' in b
 assert b'Content-Type: image/jpeg' in b
 assert b'RGNEWSBOUNDARY--' in b
 print(json.dumps({'status':'MULTIPART_SELFTEST_PASS','telegram_calls':0,'publications':0}))
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['preflight']:print(json.dumps(check(),ensure_ascii=False))
  else:raise RuntimeError('ONLY_SELFTEST_OR_PREFLIGHT')
 except Exception as e:
  reason=str(e)
  if any(c in reason for c in (':','https','token','/volume1')):reason=type(e).__name__
  print(json.dumps({'status':'SAFE_STOP','reason':reason,'telegram_sends':0,'publications':0}))
  sys.exit(2)
