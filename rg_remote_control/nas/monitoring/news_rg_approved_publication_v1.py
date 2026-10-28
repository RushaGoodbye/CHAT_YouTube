#!/usr/bin/env python3
"""NEWS RG public publisher: ONLY new human-accepted private Telegram cards.

Uses the already installed moderator bot, an explicitly grounded channel, and
the exact Telegram photo file_id from the private moderation message.
No getUpdates, no extra poller. Durable pre-send receipts prevent blind retries.
"""
import os,sys,re,json,time,pathlib,tempfile,urllib.request,urllib.parse,urllib.error,importlib.util,fcntl,hashlib
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
ACT=O/'news_rg_publication_activation_v1.json'
PUB=O/'news_rg_publication_receipts_v1'
DEC=O/'news_rg_editorial_decisions_v1'
SENT=O/'news_rg_private_multipart_receipts_v1'
STAGED=O/'news_rg_private_review_staging'
LCK=O/'news_rg_publication.lock'
CHANNEL_KEYS=('RG_NEWS_PUBLIC_CHANNEL_ID','RG_TELEGRAM_CHANNEL_ID','TELEGRAM_CHANNEL_ID','PUBLIC_CHANNEL_ID','PUBLISH_CHAT_ID')
CFG_KEYS=('public_channel_id','publication_channel_id','channel_id','target_channel_id','publish_chat_id')
def fail(s):raise RuntimeError(s)
def emit(**a):print(json.dumps(a,ensure_ascii=False,sort_keys=True))
def read_json(p,max_bytes=24000):
 if not p.is_file() or p.is_symlink() or p.stat().st_size>max_bytes:fail('UNSAFE_FILE_'+p.name)
 return json.loads(p.read_text('utf-8'))
def persist(p,d,exclusive=False):
 content=json.dumps(d,ensure_ascii=False,sort_keys=True).encode('utf-8')
 if exclusive:
  fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
  return
 fd,tmp=tempfile.mkstemp(prefix='.news_rg_pub_',dir=str(p.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),0o600);f.write(content);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def module():
 p=B/'rg_moderation.py'
 if not p.is_file() or p.is_symlink() or '# NEWS_RG_EDITORIAL_HOOK_V1' not in p.read_text('utf-8'):
  fail('PRODUCTION_MODERATOR_MODULE_CHANGED')
 spec=importlib.util.spec_from_file_location('_news_rg_publisher_mod',str(p))
 m=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(m)
 cfg=m.config()
 return cfg
def parse_channel(value):
 if isinstance(value,bool):return None
 v=str(value).strip()
 if re.fullmatch(r'-100\d{7,15}',v):return v
 if re.fullmatch(r'@[A-Za-z0-9_]{5,32}',v):return v
 return None
def discover_channel(cfg):
 found=set()
 for k in CHANNEL_KEYS:
  if os.environ.get(k):
   parsed=parse_channel(os.environ[k])
   if not parsed:fail('UNSAFE_CHANNEL_ENV_FORMAT_'+k)
   found.add(parsed)
 for k in CFG_KEYS:
  if cfg.get(k) is not None:
   parsed=parse_channel(cfg[k])
   if parsed:found.add(parsed)
 # Only known channel-specific keys, never generic chat IDs or source feed channels.
 if len(found)!=1:fail('CHANNEL_NOT_UNAMBIGUOUS_IN_EXISTING_CONFIG')
 return found.pop()
def credentials():
 p=O/'news_rg_multipart.py'
 if not p.is_file() or p.is_symlink():fail('PRIVATE_BOT_TRANSPORT_NOT_INSTALLED')
 sp=importlib.util.spec_from_file_location('_news_rg_multipart',str(p))
 m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
 return m.token()
def telegram(method,payload,token):
 url='https://api.telegram.org/bot'+token+'/'+method
 post=urllib.parse.urlencode(payload).encode('utf-8')
 req=urllib.request.Request(url,data=post,headers={'Content-Type':'application/x-www-form-urlencoded'})
 with urllib.request.urlopen(req,timeout=30) as resp: data=json.loads(resp.read(60000))
 if data.get('ok') is not True or not isinstance(data.get('result'),(dict,list)):
  fail('TELEGRAM_API_REJECTED_'+method)
 return data['result']
def verify_channel(cfg,token):
 dest=discover_channel(cfg)
 me=telegram('getMe',{},token)
 identity=me.get('id')
 if not isinstance(identity,int):fail('BOT_ID_UNVERIFIED')
 info=telegram('getChat',{'chat_id':dest},token)
 if info.get('type')!='channel' or not isinstance(info.get('id'),int):
  fail('DESTINATION_NOT_CHANNEL')
 destid=info['id']
 if not str(destid).startswith('-100'):fail('DESTINATION_ID_INVALID')
 if str(cfg.get('moderation_chat_id'))==str(destid):fail('DEST_EQUALS_MODERATOR')
 member=telegram('getChatMember',{'chat_id':destid,'user_id':identity},token)
 if member.get('status')!='administrator' or member.get('can_post_messages') is not True:
  fail('BOT_NOT_VERIFIED_CHANNEL_POSTING_ADMIN')
 return {'chat_id':destid,'bot_id':identity,'title':str(info.get('title',''))[:100],
         'channel_name':str(info.get('username',''))[:45]}
def gate():
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 if not ACT.exists():fail('PUBLICATION_NOT_ACTIVATED')
 a=read_json(ACT,10000)
 if a.get('status')!='ACTIVE' or a.get('schema')!='NEWS_RG_PUBLICATION_ACTIVATION_V1':
  fail('PUBLICATION_NOT_ACTIVE')
 if not isinstance(a.get('activated_at'),int) or a['activated_at']<1700000000:fail('ACTIVATION_TIMESTAMP_UNSAFE')
 if not isinstance(a.get('chat_id'),int) or str(a['chat_id'])[:4]!='-100':fail('ACTIVATION_DESTINATION_INVALID')
 if not isinstance(a.get('bot_id'),int):fail('ACTIVATION_BOT_ID_INVALID')
 if not STAGED.is_dir() or STAGED.is_symlink():fail('STAGED_DIR_UNSAFE')
 for path in (O/'rg_news2_p31_guarded_callback_once.py',O/'news_rg_editorial_callbacks_v1.py'):
  if not path.is_file() or path.is_symlink():fail('EDITORIAL_COMPONENT_MISSING')
 if '# NEWS_RG_NE1_OWNER_ROUTE_V1' not in (O/'rg_news2_p31_guarded_callback_once.py').read_text():
  fail('EDITORIAL_ROUTING_NOT_VERIFIED')
 return a
def choose(act,now=None):
 now=int(time.time()) if now is None else now
 if not DEC.is_dir() or DEC.is_symlink() or not SENT.is_dir() or SENT.is_symlink():fail('DECISION_OR_RECEIPT_DIR_UNSAFE')
 if not PUB.is_dir() or PUB.is_symlink():fail('PUBLIC_RECEIPT_DIR_UNSAFE')
 # An uncertain send pauses the whole public queue until a human resolves it.
 for pub_receipt in PUB.glob('*.json'):
  if pub_receipt.is_symlink():fail('PUBLIC_RECEIPT_SYMLINK')
  if read_json(pub_receipt).get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':
   fail('PREVIOUS_PUBLIC_SEND_UNCERTAIN_REQUIRES_REVIEW')
 eligible=[]
 for p in DEC.glob('*.json'):
  if not re.fullmatch(r'[a-f0-9]{24}\.json',p.name) or p.is_symlink():continue
  d=read_json(p)
  if d.get('decision')!='editorially_accepted_not_published':continue
  if d.get('public_publication')!='OFF' or d.get('schema')!='NEWS_RG_HUMAN_EDITORIAL_DECISION_V1':continue
  decision_at=d.get('timestamp')
  # NEVER publish historical decisions. Also halt stale stories.
  if not isinstance(decision_at,int) or decision_at<=act['activated_at'] or now-decision_at>24*3600 or decision_at>now+60:continue
  key=p.stem
  if d.get('draft_id')!=key or not isinstance(d.get('moderator_id'),int):continue
  if (PUB/(key+'.json')).exists():continue
  receipt=read_json(SENT/(key+'.json'))
  if receipt.get('status')!='PRIVATE_SENT_CONFIRMED' or receipt.get('draft_id')!=key or receipt.get('message_id')!=d.get('telegram_message_id'):continue
  if receipt.get('public_publication')!='OFF':continue
  file_id=receipt.get('telegram_photo_file_id')
  if not isinstance(file_id,str) or not 15<=len(file_id)<=255 or not re.fullmatch(r'[A-Za-z0-9_-]+',file_id):continue
  st=read_json(STAGED/(key+'.json'))
  if st.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or st.get('draft_id')!=key:continue
  if st.get('public_publication')!='OFF' or st.get('editorial_status')!='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED':continue
  caption=str(st.get('proposed_text','')).strip()
  if not 60<=len(caption)<=900 or 'НЕВДАЛО' in caption.upper() or any(ch in caption for ch in 'ыъэёЫЪЭЁ'):continue
  eligible.append((decision_at,key,file_id,caption))
 eligible.sort()
 return eligible[0] if eligible else None
def publish_one():
 act=gate()
 PUB.mkdir(mode=0o700,exist_ok=True)
 # Every send is claimed BEFORE the Telegram request; uncertain sends never retried.
 fd=os.open(str(LCK),os.O_CREAT|os.O_RDWR,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX)
  selected=choose(act)
  if selected is None:return {'status':'NO_APPROVED_NEW_STORY','publications':0}
  decision_at,key,photo,caption=selected
  cfg=module();token=credentials()
  channel=verify_channel(cfg,token)
  if channel['chat_id']!=act['chat_id'] or channel['bot_id']!=act['bot_id']:
   fail('PINNED_PUBLICATION_IDENTITY_CHANGED')
  receipt=PUB/(key+'.json')
  if receipt.exists() or receipt.is_symlink():fail('PUBLICATION_ALREADY_CLAIMED')
  persist(receipt,{'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY','draft_id':key,
    'channel_id':act['chat_id'],'claimed_at':int(time.time()),
    'decision_timestamp':decision_at},exclusive=True)
  try:
   result=telegram('sendPhoto',{'chat_id':act['chat_id'],'photo':photo,
                   'caption':caption,'disable_notification':'false'},token)
   if (not isinstance(result.get('message_id'),int) or
       int((result.get('chat') or {}).get('id',0))!=act['chat_id']):
    fail('PUBLIC_SEND_ACK_MISMATCH')
   persist(receipt,{'status':'PUBLIC_PUBLISHED_CONFIRMED','draft_id':key,
    'channel_id':act['chat_id'],'message_id':result['message_id'],
    'published_at':int(time.time()),'decision_timestamp':decision_at})
   return {'status':'PUBLIC_PUBLISHED_CONFIRMED','draft_id':key,
      'message_id':result['message_id'],'publications':1}
  except Exception:
   # Never retry uncertain send: it may already exist on Telegram.
   return {'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY','draft_id':key,
      'publications_confirmed':0,'automatic_retry':False}
 finally:
  os.close(fd)
def status():
 try:
  act=gate();selected=choose(act)
  confirmed=0;uncertain=0
  if PUB.is_dir():
   for p in PUB.glob('*.json'):
    if not p.is_file() or p.is_symlink():continue
    item=read_json(p)
    confirmed+=item.get('status')=='PUBLIC_PUBLISHED_CONFIRMED'
    uncertain+=item.get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY'
  return {'status':'ACTIVE','pinned_channel_id':act['chat_id'],
    'new_approved_ready':bool(selected),'published_confirmed':confirmed,
    'uncertain_needs_review':uncertain,'old_approvals_replayed':False}
 except Exception as e:return {'status':'PAUSED','reason':str(e)[:90],
                                'publications':0}
def selftest():
 import tempfile
 assert parse_channel(-1001234567890)=='-1001234567890'
 assert parse_channel('@Channel_123')=='@Channel_123'
 assert parse_channel('123456789') is None
 with tempfile.TemporaryDirectory() as d:
  root=pathlib.Path(d)
  global DEC,SENT,STAGED,PUB
  DEC=root/'dec';SENT=root/'sent';STAGED=root/'stage';PUB=root/'published'
  for p in (DEC,SENT,STAGED,PUB):p.mkdir()
  key='a'*24;act={'activated_at':1000}
  decision={'schema':'NEWS_RG_HUMAN_EDITORIAL_DECISION_V1','draft_id':key,
   'decision':'editorially_accepted_not_published','public_publication':'OFF',
   'moderator_id':123,'telegram_message_id':12,'timestamp':1001}
  receipt={'status':'PRIVATE_SENT_CONFIRMED','draft_id':key,'message_id':12,
    'public_publication':'OFF','telegram_photo_file_id':'A'*30}
  draft={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1','draft_id':key,
    'public_publication':'OFF','editorial_status':'HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED',
    'proposed_text':'Відредагована українська новина з атрибуцією до джерела для перевірки читачем.'}
  for dir,obj in ((DEC,decision),(SENT,receipt),(STAGED,draft)):
   (dir/(key+'.json')).write_text(json.dumps(obj))
  assert choose(act,now=1002)[1]==key
  (PUB/(key+'.json')).write_text('{}')
  assert choose(act,now=1002) is None
  (PUB/(key+'.json')).unlink()
  decision['timestamp']=999;(DEC/(key+'.json')).write_text(json.dumps(decision))
  assert choose(act,now=1002) is None
 print('NEWS_RG_PUBLICATION_PUBLISHER_SELFTEST_PASS')
if __name__=='__main__':
 try:
  args=sys.argv[1:]
  if args==['selftest']:selftest()
  elif args==['status']:emit(**status())
  elif args==['publish-one']:emit(**publish_one())
  elif args==['channel-check']:
   if os.geteuid()!=0:fail('SUDO_REQUIRED')
   channel=verify_channel(module(),credentials())
   emit(status='PUBLIC_CHANNEL_VERIFIED',channel_title=channel['title'],
        channel_id=channel['chat_id'],bot_admin_can_post=True,
        telegram_sends=0,publications=0)
  else:fail('BAD_MODE')
 except Exception as exc:
  emit(status='SAFE_STOP',reason=str(exc)[:110],publications=0)
  sys.exit(2)
