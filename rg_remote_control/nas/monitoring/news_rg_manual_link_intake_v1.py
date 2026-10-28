#!/usr/bin/env python3
"""Restore MANUAL public Telegram link intake inside the SINGLE existing NAS update worker.

No polling, no second Telegram owner, no automatic public publishing.
A valid link produces only a review-required staging sidecar; existing
at-most-once private dispatcher sends a card. The human alone approves public
publication. Uses a self-contained public Telegram post parser, no legacy bot imports.
"""
import os,sys,json,re,time,hashlib,pathlib,urllib.parse,urllib.request,urllib.error,html,socket,ipaddress,subprocess
from html.parser import HTMLParser
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
ST=O/'news_rg_private_review_staging'
ACT=O/'news_rg_manual_link_activation_v1.json'
DISPATCH=O/'news_rg_durable_private_dispatch_v1.py'
LOG=O/'news_rg_manual_link_dispatch_v1.log'
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
class PublicPostReader(HTMLParser):
 """Read exactly one public Telegram embed post, not the site's OG previews."""
 def __init__(self,channel,num):
  super().__init__(convert_charrefs=True)
  self.expected=channel+'/'+num
  self.active=False;self.depth=0;self.text_depth=0
  self.body=[];self.photo=''
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if not self.active:
   if d.get('data-post')==self.expected and 'tgme_widget_message' in d.get('class','').split():
    self.active=True;self.depth=1
   return
  if tag in ('br','hr','img','meta','input','link','source'):
   if tag=='br' and self.text_depth:self.body.append(' ')
   return
  self.depth+=1
  cl=d.get('class','').split()
  if 'tgme_widget_message_text' in cl:self.text_depth=self.depth
  if 'tgme_widget_message_photo_wrap' in cl:
   match=re.search(r'background-image\s*:\s*url\(\s*["\']?(https://[^)\s"\']+)',d.get('style',''),re.I)
   if match:
    photo=html.unescape(match.group(1))
    if photo_ok(photo):self.photo=photo
 def handle_data(self,data):
  if self.active and self.text_depth:self.body.append(data)
 def handle_endtag(self,tag):
  if not self.active or tag in ('br','hr','img','meta','input','link','source'):return
  if self.text_depth==self.depth:self.text_depth=0
  self.depth-=1
  if self.depth<=0:self.active=False
 def parsed(self):
  return ' '.join(html.unescape(' '.join(self.body)).split()),self.photo
class CanonicalMeta(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.meta={}
 def handle_starttag(self,tag,attrs):
  if tag!='meta':return
  a=dict(attrs);k=a.get('property') or a.get('name')
  if k and isinstance(a.get('content'),str):self.meta.setdefault(k,a['content'])
 def get(self,key):return self.meta.get(key,'')
class BlockRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise ValueError('TELEGRAM_REDIRECT_BLOCKED')
def fetch_telegram_html(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0',
    'Accept':'text/html'})
 try:
  with urllib.request.build_opener(BlockRedirect()).open(req,timeout=10) as resp:
   typ=resp.headers.get('Content-Type','').lower()
   if 'text/html' not in typ:raise ValueError('NOT_HTML')
   raw=resp.read(200001)
 except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,OSError):
  raise ValueError('SOURCE_UNAVAILABLE') from None
 if len(raw)>200000:raise ValueError('HTML_TOO_BIG')
 return raw.decode('utf8','replace')
def from_canonical(html_page,channel,num):
 """The canonical post has OG text + photo/video preview even for video posts."""
 meta=CanonicalMeta();meta.feed(html_page)
 expected='https://t.me/'+channel+'/'+num
 android=meta.get('twitter:app:url:googleplay')
 alternate=meta.get('al:android:url')
 # Never trust a site-wide OG preview or media from a different post.
 marker_match=(android==expected or
    alternate=='tg://resolve?domain='+channel+'&post='+num)
 if not marker_match:raise ValueError('CANONICAL_POST_ID_NOT_VERIFIED')
 text=' '.join(html.unescape(meta.get('og:description') or '').split())
 photo=html.unescape(meta.get('og:image'))
 if not 60<=len(text)<=900:raise ValueError('CANONICAL_TEXT_MISSING')
 if not photo_ok(photo):raise ValueError('CANONICAL_MEDIA_PREVIEW_MISSING')
 return text,photo
def source_to_post(url):
 """Public t.me post: canonical OG for photo AND video thumbnail; embed fallback."""
 parts=urllib.parse.urlsplit(url)
 if parts.scheme!='https' or parts.hostname!='t.me':raise ValueError('INVALID_HOST')
 tokens=parts.path.strip('/').split('/')
 if len(tokens)!=2 or not VALID_CHANNEL.fullmatch(tokens[0]) or not VALID_POST.fullmatch(tokens[1]):
  raise ValueError('INVALID_POST')
 try:
  addresses=[ipaddress.ip_address(r[4][0]) for r in
    socket.getaddrinfo('t.me',443,type=socket.SOCK_STREAM)]
 except (OSError,ValueError):raise ValueError('SOURCE_DNS_FAILED') from None
 if not addresses or any(not address.is_global for address in addresses):
  raise ValueError('SOURCE_DNS_NOT_PUBLIC')
 errors=[]
 try:
  body,photo=from_canonical(fetch_telegram_html(url),tokens[0],tokens[1])
  return body[:100].rsplit(' ',1)[0],body,photo
 except (ValueError,UnicodeError) as e:errors.append(type(e).__name__)
 embed='https://t.me/'+tokens[0]+'/'+tokens[1]+'?embed=1'
 reader=PublicPostReader(tokens[0],tokens[1])
 reader.feed(fetch_telegram_html(embed))
 body,photo=reader.parsed()
 if not 60<=len(body)<=900:raise ValueError('NO_COMPLETE_POST_TEXT')
 if not photo:raise ValueError('NO_ALLOWED_POST_MEDIA_PREVIEW')
 return body[:100].rsplit(' ',1)[0],body,photo
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
  title,text,photo=source_to_post(link)
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

 html_sample=('<div class="tgme_widget_message" data-post="Some_Channel/123">'
  '<div class="tgme_widget_message_text">За повідомленням міської ради, у місті відкрили новий пункт допомоги. '
  'Подробиці повідомлять додатково.</div>'
  '<a class="tgme_widget_message_photo_wrap" style="background-image:url(&#39;https://cdn3.telesco.pe/file/test.jpg&#39;)"></a></div>')
 parser=PublicPostReader('Some_Channel','123')
 parser.feed(html_sample)
 value,photo=parser.parsed()
 assert 'За повідомленням' in value
 assert photo=='https://cdn3.telesco.pe/file/test.jpg'
 wrong=PublicPostReader('Some_Channel','124')
 wrong.feed(html_sample)
 assert wrong.parsed()==('', '')
 assert not photo_ok('https://evil.example/photo.jpg')
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
