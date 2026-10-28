#!/usr/bin/env python3
"""Restore MANUAL public Telegram link intake inside the SINGLE existing NAS update worker.

No polling, no second Telegram owner, no automatic public publishing.
A valid link produces only a review-required staging sidecar; existing
at-most-once private dispatcher sends a card. The human alone approves public
publication. Reuses the pinned former parser, WITHOUT starting its bot.
"""
import os,sys,json,re,time,hashlib,pathlib,urllib.parse,importlib.util,tempfile,subprocess
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
ST=O/'news_rg_private_review_staging'
OLD=pathlib.Path('/volume1/docker/RG_TELEGRAM_STATE/rg_telegram_nas_native_bot_v01.py')
ACT=O/'news_rg_manual_link_activation_v1.json'
DISPATCH=O/'news_rg_durable_private_dispatch_v1.py'
LOG=O/'news_rg_manual_link_dispatch_v1.log'
OLD_SHA_PREFIX='a2512586b44cac'
VALID_CHANNEL=re.compile(r'^[A-Za-z_][A-Za-z0-9_]{3,}$')
VALID_POST=re.compile(r'^\d{1,15}$')
TELEGRAM_HOSTS=('t.me','telegram.me')
MEDIA_HOSTS=('cdn1.telesco.pe','cdn2.telesco.pe','cdn3.telesco.pe',
             'cdn4.telesco.pe','cdn5.telesco.pe')
MARK='NEWS_RG_MANUAL_LINK_INTAKE_V1'
def err(s):raise RuntimeError(s)
def read(p,limit=20000):
 if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:err('UNSAFE_FILE')
 return json.loads(p.read_text('utf8'))
def link_from_text(s):
 if not isinstance(s,str):return None
 for match in re.finditer(r'https://(?:t\.me|telegram\.me)/[^\s<>"\']+',s,re.I):
  candidate=match.group(0).rstrip('.,!;:»”)]}')
  try:
   parsed=urllib.parse.urlsplit(candidate)
  except ValueError:continue
  if parsed.scheme!='https' or parsed.hostname not in TELEGRAM_HOSTS:
   continue
  if parsed.username or parsed.password or parsed.port is not None:continue
  pieces=parsed.path.strip('/').split('/')
  if len(pieces)==3 and pieces[0]=='s':pieces=pieces[1:]
  if len(pieces)!=2 or not VALID_CHANNEL.fullmatch(pieces[0]) or not VALID_POST.fullmatch(pieces[1]):
   continue
  return 'https://t.me/'+pieces[0]+'/'+str(int(pieces[1]))
 return None
def loader():
 if OLD.is_symlink() or not OLD.is_file() or OLD.stat().st_size>100000:err('LEGACY_PARSER_UNAVAILABLE')
 content=OLD.read_bytes()
 if not hashlib.sha256(content).hexdigest().startswith(OLD_SHA_PREFIX):
  err('LEGACY_PARSER_HASH_CHANGED')
 spec=importlib.util.spec_from_file_location('_newsrg_readonly_legacy_parser',str(OLD))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 if not callable(getattr(m,'source_to_post',None)):err('LEGACY_PARSER_FUNCTION_MISSING')
 return m
def moderator(msg,cfg):
 chat=msg.get('chat') or {}
 user=msg.get('from') or {}
 if not isinstance(cfg,dict) or chat.get('type')!='private':return False
 try:
  user_id=int(user.get('id',0));chat_id=int(chat.get('id',0))
  allowed={int(v) for v in cfg.get('moderators') or []}
  expected=int(cfg.get('moderation_chat_id',0))
  return user_id>0 and user_id==chat_id and user_id==expected and user_id in allowed
 except (ValueError,TypeError):return False
def photo_ok(url):
 if not isinstance(url,str) or len(url)>3000:return False
 try:
  p=urllib.parse.urlsplit(url)
  return p.scheme=='https' and p.hostname in MEDIA_HOSTS and not p.username and not p.password and p.port in (None,443) and bool(p.path)
 except ValueError:return False
def text_ok(text):
 return isinstance(text,str) and 85<=len(text)<=700 and (
  not any(c in text for c in 'ыъэёЫЪЭЁ')) and 'НЕВДАЛО' not in text.upper()
def atomic_exclusive(p,obj):
 content=json.dumps(obj,ensure_ascii=False,sort_keys=True).encode('utf8')
 fd=os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'wb') as h:h.write(content);h.flush();os.fsync(h.fileno())
def stage(url,text,photo,message_date):
 if not photo_ok(photo):return {'status':'MANUAL_PHOTO_UNSUPPORTED'}
 if not text_ok(text):return {'status':'MANUAL_REQUIRES_UKRAINIAN_FULL_TEXT'}
 if ST.is_symlink() or not ST.is_dir():err('STAGING_UNAVAILABLE')
 key=hashlib.sha256(('NEWS_RG_MANUAL_LINK_V1\0'+url).encode('utf8')).hexdigest()[:24]
 p=ST/(key+'.json')
 if p.is_symlink():err('STAGING_SYMLINK')
 if p.exists():return {'status':'MANUAL_LINK_ALREADY_QUEUED','draft_id':key}
 data={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1',
   'draft_id':key,'source_key':'manual:'+url,'channel':'manual_link',
   'posted_at':message_date,'media_url':photo,
   'original_text':text,'proposed_text':text,
   'editorial_status':'HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED',
   'photo_approval_is_not_editorial_approval':True,
   'telegram_delivery':'NOT_SENT','public_publication':'OFF',
   'prepared_at':int(time.time()),
   'manual_submission':True}
 try:atomic_exclusive(p,data)
 except FileExistsError:return {'status':'MANUAL_LINK_ALREADY_QUEUED','draft_id':key}
 return {'status':'MANUAL_LINK_STAGED','draft_id':key}
def reply(api,chat_id,text):
 # A Telegram acknowledgment is useful, but should not stop a staged sidecar.
 try:
  api('sendMessage',{'chat_id':chat_id,'text':text})
  return True
 except Exception:return False
def handle(update,cfg,api):
 """Called ONLY for 'message' by the existing singleton update worker."""
 msg=update.get('message')
 if not isinstance(msg,dict):return {'status':'NOT_A_MESSAGE'}
 if not moderator(msg,cfg):return {'status':'MANUAL_UNAUTHORIZED_IGNORED'}
 act=read(ACT)
 if act.get('schema')!='NEWS_RG_MANUAL_LINK_ACTIVATION_V1' or act.get('status')!='ACTIVE':
  return {'status':'MANUAL_GATE_CLOSED'}
 date=msg.get('date')
 if not isinstance(date,int) or date<act.get('activated_at',0)-2:
  return {'status':'MANUAL_OLD_UPDATE_EXCLUDED'}
 chat=int((msg.get('chat') or {})['id'])
 raw=msg.get('text') or msg.get('caption') or ''
 link=link_from_text(raw)
 if link is None:
  reply(api,chat,'Надішли посилання на відкритий пост Telegram з фото та повним текстом (t.me/канал/номер).')
  return {'status':'MANUAL_HELP_SENT'}
 try:
  legacy=loader()
  title,text,photo=legacy.source_to_post(link)
 except Exception:
  reply(api,chat,'⚠️ Не вдалося отримати повний текст і фото з відкритої публікації. Перевір, чи доступний пост без авторизації.')
  return {'status':'MANUAL_SOURCE_NOT_ACCESSIBLE'}
 result=stage(link,text,photo,date)
 st=result['status']
 if st=='MANUAL_LINK_STAGED':
  reply(api,chat,'✅ Посилання прийнято. Новина надійде на приватну перевірку; без твого схвалення публікації не буде.')
 elif st=='MANUAL_LINK_ALREADY_QUEUED':
  reply(api,chat,'ℹ️ Цю новину вже додано до черги модерації. Повторної публікації не буде.')
 elif st=='MANUAL_REQUIRES_UKRAINIAN_FULL_TEXT':
  reply(api,chat,'⚠️ Автоматично зберегти текст не вдалося: потрібен повний український текст. Новину не опубліковано.')
 elif st=='MANUAL_PHOTO_UNSUPPORTED':
  reply(api,chat,'⚠️ Джерело не надало придатне фото. Новину не опубліковано.')
 return result
def dispatch_once_async():
 """Only a one-shot PRIVATE sender, no getUpdates, no public send."""
 if DISPATCH.is_symlink() or not DISPATCH.is_file():return False
 if LOG.is_symlink():return False
 try:
  with LOG.open('ab') as log:
   subprocess.Popen(['/usr/bin/python3',str(DISPATCH),'run-once'],
    stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  return True
 except (OSError,ValueError):return False
def selftest():
 assert link_from_text('https://t.me/Some_Channel/123?single')=='https://t.me/Some_Channel/123'
 assert link_from_text('https://t.me/s/Some_Channel/123')=='https://t.me/Some_Channel/123'
 assert link_from_text('https://t.me/c/123456/89') is None
 assert link_from_text('https://example.com/abc') is None
 assert link_from_text('https://t.me/channel') is None
 assert photo_ok('https://cdn4.telesco.pe/file/a.jpg')
 assert not photo_ok('https://example.com/img.png')
 assert not photo_ok('http://cdn4.telesco.pe/a')
 cfg={'moderators':[123],'moderation_chat_id':123}
 good={'chat':{'type':'private','id':123},'from':{'id':123}}
 assert moderator(good,cfg)
 assert not moderator({'chat':{'type':'group','id':123},'from':{'id':123}},cfg)
 assert not moderator(good,{'moderators':[321],'moderation_chat_id':123})
 import tempfile
 global ST
 old=ST
 try:
  with tempfile.TemporaryDirectory() as tmp:
   ST=pathlib.Path(tmp)
   body='За повідомленням міської ради, у місті відкрили новий пункт допомоги. Подробиці повідомлять додатково.'
   url='https://t.me/Some_Channel/123'
   a=stage(url,body,'https://cdn2.telesco.pe/file/test.jpg',int(time.time()))
   assert a['status']=='MANUAL_LINK_STAGED'
   b=stage(url,body,'https://cdn2.telesco.pe/file/test.jpg',int(time.time()))
   assert b['status']=='MANUAL_LINK_ALREADY_QUEUED'
   obj=json.loads((ST/(a['draft_id']+'.json')).read_text('utf8'))
   assert obj['public_publication']=='OFF' and obj['editorial_status']=='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED'
 finally:ST=old
 print('NEWS_RG_MANUAL_LINK_INTAKE_SELFTEST_PASS')
if __name__=='__main__':
 if sys.argv[1:]==['selftest']:selftest()
 else:raise SystemExit('SELFTEST_ONLY_NO_POLLING')
