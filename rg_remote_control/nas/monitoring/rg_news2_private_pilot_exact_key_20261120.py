#!/usr/bin/env python3
"""NEWS2 single-shot private QA via EXISTING news_rg_multipart transport.
No live module imports; no getUpdates; no public sendPoll/sendPhoto; no new pollers.
Output never includes bot token, private chat ID or exact secret path.
"""
import ast,fcntl,hashlib,json,os,pathlib,re,stat,sys,time,urllib.request,urllib.error,uuid
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=ROOT/'operator'
POLL=OP/'news_rg_poll_moderation_v1.py'
CFG=ROOT/'moderation.json'
RELEASE=OP/'news_rg_stability_releases_v1/pinned_release_v1.json'
RECEIPT=OP/'news_rg_stability_releases_v1/rg_poll_private_pilot_receipt.json'
LOCK=OP/'news_rg_stability_releases_v1/rg_poll_private_pilot.lock'
EXPECT_SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
TOKEN_RE=re.compile(r'^[0-9]{8,12}:[A-Za-z0-9_-]{30,55}$')
BOT='russiagoodbyenewsbot'
def demand(ok,reason):
 if not ok:raise RuntimeError(reason)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verified_transport():
 # The pinned poll module uses news_rg_multipart.token()/identity(), NOT
 # its Gemini API KEY. Import the existing shared Telegram transport.
 import importlib
 sys.path.insert(0,str(OP))
 transport=importlib.import_module('news_rg_multipart')
 demand(callable(getattr(transport,'token',None)) and
        callable(getattr(transport,'identity',None)),
        'EXISTING_TELEGRAM_TRANSPORT_UNAVAILABLE')
 token=transport.token()
 identity=transport.identity()
 demand(isinstance(token,str) and bool(TOKEN_RE.fullmatch(token)),
        'EXISTING_TELEGRAM_TRANSPORT_BAD_TOKEN')
 return token,identity
def api(token,method,data):
 request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,
  data=json.dumps(data,ensure_ascii=False).encode('utf8'),
  headers={'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(request,timeout=14) as response:answer=json.load(response)
 except urllib.error.HTTPError as e:
  raise RuntimeError('TELEGRAM_'+method+'_HTTP_'+str(e.code))
 except Exception as e:
  raise RuntimeError('TELEGRAM_'+method+'_TRANSPORT_'+type(e).__name__)
 demand(answer.get('ok') is True,'TELEGRAM_'+method+'_NOT_OK')
 return answer.get('result')
def preflight():
 demand(os.geteuid()==0,'ROOT_REQUIRED')
 demand(sys.version_info[:2]==(3,15),'PYTHON_315_REQUIRED')
 for p in (POLL,CFG,RELEASE):
  demand(p.is_file() and not p.is_symlink(),'MISSING_OR_UNSAFE_'+p.name)
 demand(sha(POLL)==EXPECT_SHA,'POLL_PROTECTION_DRIFT')
 release=json.loads(RELEASE.read_text(encoding='utf8'))
 demand(release.get('files',{}).get(POLL.name)==EXPECT_SHA,'PINNED_RELEASE_DRIFT')
 config=json.loads(CFG.read_text(encoding='utf8'))
 chat_id=config.get('moderation_chat_id')
 moderators=config.get('moderators')
 demand(isinstance(chat_id,int) and chat_id>0,'INVALID_MODERATOR_PRIVATE_CHAT')
 demand(isinstance(moderators,list) and chat_id in [int(x) for x in moderators],'MODERATOR_NOT_ALLOWED')
 return chat_id
def receipt_status():
 if RECEIPT.exists():
  demand(RECEIPT.is_file() and not RECEIPT.is_symlink(),'RECEIPT_UNSAFE')
  data=json.loads(RECEIPT.read_text(encoding='utf8'))
  if data.get('status')=='SENT_PRIVATE':
   return {'status':'PRIVATE_TEST_ALREADY_SENT_NO_DUPLICATE','private_message_id':data.get('message_id')}
  return {'status':'PRIVATE_TEST_PREVIOUS_ATTEMPT_UNCERTAIN_NO_RETRY'}
 return None
def send():
 chat_id=preflight()
 lock=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
 fcntl.flock(lock,fcntl.LOCK_EX)
 try:
  previous=receipt_status()
  if previous:return previous
  token,transport_identity=verified_transport()
  # identity() is the existing transport's identity marker, not necessarily a chat ID.
  demand(transport_identity is not None,'TELEGRAM_TRANSPORT_IDENTITY_MISSING')
  me=api(token,'getMe',{})
  demand(isinstance(me,dict) and str(me.get('username','')).lower()==BOT,
   'POLL_TOKEN_NOT_RUSSIA_GOODBYE_NEWS_BOT')
  chat=api(token,'getChat',{'chat_id':chat_id})
  demand(isinstance(chat,dict) and chat.get('type')=='private' and chat.get('id')==chat_id,
   'MODERATOR_CHAT_NOT_VERIFIED_PRIVATE')
  # Random nonexistent id: it can never correspond to a saved draft; real approval is fail-closed.
  unique='qa'+uuid.uuid4().hex
  text=('🧪 ПРИВАТНИЙ ТЕСТ МОДЕРАЦІЇ · РАША ГУДБАЙ\n\n'
        'Ця картка не є новиною чи опитуванням. Публікацію вимкнено.\n'
        'Кнопки містять тестовий ID, якого немає в редакційній черзі.\n\n'
        'Натисніть одну тестову кнопку та повідомте, що відбулося.')
  keyboard={'inline_keyboard':[
   [{'text':'✅ ТЕСТ ПУБЛІКАЦІЇ','callback_data':'rp1:pub:'+unique}],
   [{'text':'🔄 ТЕСТ ПЕРЕРОБКИ','callback_data':'rp1:redo:'+unique}],
   [{'text':'❌ ТЕСТ ВІДХИЛЕННЯ','callback_data':'rp1:reject:'+unique}]]}
  # Exact-once attempt record BEFORE Telegram send. Never auto-retry on uncertain result.
  record={'status':'SEND_ATTEMPTED_NO_RETRY','created_at':int(time.time()),
          'test_id_sha256':hashlib.sha256(unique.encode('utf8')).hexdigest()}
  fd=os.open(str(RECEIPT),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(fd,'w',encoding='utf8') as f:
   json.dump(record,f);f.flush();os.fsync(f.fileno())
  try:
   message=api(token,'sendMessage',{'chat_id':chat_id,'text':text,'reply_markup':keyboard})
   demand(isinstance(message,dict) and isinstance(message.get('message_id'),int) and
     message.get('chat',{}).get('id')==chat_id,'PRIVATE_MESSAGE_RECEIPT_UNEXPECTED')
  except Exception as e:
   return {'status':'PRIVATE_SEND_UNCERTAIN_NO_RETRY','reason':str(e)[:110]}
  record.update({'status':'SENT_PRIVATE','message_id':message['message_id']})
  tmp=RECEIPT.with_name('.rg_poll_private_pilot_receipt_temp')
  with open(tmp,'w',encoding='utf8') as f:
   os.chmod(tmp,0o600);json.dump(record,f);f.flush();os.fsync(f.fileno())
  os.replace(tmp,RECEIPT)
  return {'status':'ONE_PRIVATE_TEST_CARD_SENT','message_id':message['message_id']}
 finally:os.close(lock)
if __name__=='__main__':
 try:
  answer=send()
  answer.update({'bot':'@RussiaGoodbyeNewsBot','poll_module_v6':'PINNED',
   'publications':0,'public_send_enabled':False,
   'new_pollers':0,'getUpdates_calls':0,'cloudflare_live':'NOT_VERIFIED',
   'real_callback_delivery':'PENDING_HUMAN_TEST'})
  print(json.dumps(answer,ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_NEWS2_PRIVATE_PILOT_SAFE_STOP','reason':str(e)[:160],
   'publications':0,'new_pollers':0,'getUpdates_calls':0},ensure_ascii=False));sys.exit(2)
