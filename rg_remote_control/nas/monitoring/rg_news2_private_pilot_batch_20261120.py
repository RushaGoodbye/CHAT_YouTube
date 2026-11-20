#!/usr/bin/env python3
"""RG NEWS2 one-shot private delivery pilot, with release verification and safe-stop.
No public API calls, no second poller, no cron changes, no getUpdates.
Only sends a labeled private synthetic card after verifying the correct bot AND private chat.
"""
import ast,fcntl,hashlib,json,os,pathlib,re,subprocess,sys,time,urllib.request,urllib.error,uuid
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=ROOT/'operator'
STATE=OP/'news_rg_stability_releases_v1'
RECEIPT=STATE/'rg_poll_private_pilot_receipt.json'
LOCK=STATE/'rg_poll_private_pilot.lock'
BOT='RussiaGoodbyeNewsBot'
TOKEN_RX=re.compile(r'(?<![A-Za-z0-9_-])([0-9]{8,12}:[A-Za-z0-9_-]{30,55})(?![A-Za-z0-9_-])')
CHAT_RX=re.compile(r'(?i)(?:^|["\x27\s])(?:RG_NEWS2_|NEWS_RG_|RG_POLL_|TELEGRAM_|TG_)?(?:MODERATOR_CHAT_ID|MODERATION_CHAT_ID|PRIVATE_CHAT_ID|ADMIN_CHAT_ID|OWNER_CHAT_ID|REVIEW_CHAT_ID)["\x27\s]*[:=]\s*["\x27]?(-?[0-9]{5,17})')
SKIP=('backup','archive','release','__pycache__','node_modules','venv','test','log','recovery')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,code):
 if not ok:raise RuntimeError(code)
def checked_paths():
 seen=set()
 for base in (ROOT,OP,ROOT/'config',OP/'config',ROOT/'secrets',ROOT/'private'):
  if not base.is_dir():continue
  for parent,dirs,files in os.walk(base):
   depth=len(pathlib.Path(parent).parts)-len(base.parts)
   dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('rg_news2_') and depth<2]
   for name in files:
    p=pathlib.Path(parent)/name
    if p in seen or not (name.endswith(('.env','.json','.conf','.ini','.yaml','.yml','.txt')) or name.startswith('.env')):continue
    seen.add(p)
    try:
     if p.is_symlink() or not p.is_file() or p.stat().st_size>250000:continue
     yield p,p.read_text('utf8',errors='replace')
    except (OSError,UnicodeError):pass
def secrets():
 tokens=set();chats=set()
 for p,content in checked_paths():
  tokens.update(TOKEN_RX.findall(content))
  chats.update(int(x) for x in CHAT_RX.findall(content) if int(x)>0)
 # The running DSM task may configure the moderator in a non-sensitive JSON file.
 return sorted(tokens),sorted(chats)
def api(token,method,data):
 raw=json.dumps(data,ensure_ascii=False).encode('utf8')
 req=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,raw,
          {'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=12) as r:ret=json.load(r)
 except urllib.error.HTTPError as e:
  raise RuntimeError('TELEGRAM_'+method+'_HTTP_'+str(e.code))
 except Exception as e:
  raise RuntimeError('TELEGRAM_'+method+'_NETWORK_'+type(e).__name__)
 require(ret.get('ok') is True,'TELEGRAM_'+method+'_REJECTED')
 return ret['result']
def local_batch():
 previous=OP/'news_rg_stability_releases_v1/rg_poll_batch_last_report.json'
 require(previous.is_file(),'PREVIOUS_BATCH_REPORT_MISSING')
 data=json.loads(previous.read_text('utf8'))
 require(data.get('status')=='NEWS2_POLLS_BATCH_OFFLINE_PASS_PENDING_LIVE_VERIFICATION','PREVIOUS_BATCH_NOT_PASSED')
 p=OP/'news_rg_poll_moderation_v1.py'
 meta=json.loads((STATE/'pinned_release_v1.json').read_text('utf8'))
 wanted='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
 require(sha(p)==wanted and meta.get('files',{}).get(p.name)==wanted,'PINNED_V6_CHANGED')
 src=p.read_text('utf8')
 require('POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' in src,'POLL_SEND_GUARD_MISSING')
 return {'status':'PASS','poll_sha256':wanted,'public_send_enabled':False}
def cloudflare():
 # Public GitHub code != live Worker. Do not claim it was deployed.
 return {'status':'LIVE_NOT_VERIFIED','source_slot_disabled':True,
         'source_public_send_guard_present':True,'deployment_attempted':False}
def main():
 require(os.geteuid()==0,'ROOT_REQUIRED')
 require(sys.version_info[:2]==(3,15),'PYTHON_315_REQUIRED')
 require(STATE.is_dir() and not STATE.is_symlink(),'STATE_UNSAFE')
 fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR,0o600)
 fcntl.flock(fd,fcntl.LOCK_EX)
 try:
  base={'suite':'RG_NEWS2_POLL_PRIVATE_PILOT_BATCH_V1',
   'local_batch':local_batch(),'cloudflare':cloudflare(),
   'telegram_calls_public':0,'publications':0,'second_pollers':0,'getUpdates_calls':0,
   'live_callbacks_verified':False,'public_poll_reenabled':False}
  if RECEIPT.is_file():
   prev=json.loads(RECEIPT.read_text('utf8'))
   if prev.get('status')=='SENT_PRIVATE':
    base.update({'status':'PRIVATE_TEST_ALREADY_SENT_NO_DUPLICATE','private_message_id':prev.get('message_id'),
                 'chat_id_last4':prev.get('chat_id_last4')})
    return base
  tokens,chats=secrets()
  if not tokens or not chats:
   base.update({'status':'PRIVATE_CARD_SAFE_STOP','reason':'BOT_TOKEN_OR_MODERATOR_PRIVATE_CHAT_NOT_FOUND',
               'token_candidates':len(tokens),'chat_candidates':len(chats)})
   return base
  # Choose ONLY the bot explicitly designated by the user, never a different token.
  verified=[]
  for token in tokens[:8]:
   try:
    me=api(token,'getMe',{})
    if str(me.get('username','')).lower()==BOT.lower():verified.append(token)
   except RuntimeError:pass
  if len(verified)!=1:
   base.update({'status':'PRIVATE_CARD_SAFE_STOP','reason':'EXACT_BOT_NOT_UNIQUELY_VERIFIED',
                'matching_bot_tokens':len(verified)})
   return base
  token=verified[0]
  allowed=[]
  for chat_id in chats[:12]:
   try:
    chat=api(token,'getChat',{'chat_id':chat_id})
    if chat.get('type')=='private' and int(chat.get('id',0))==chat_id:
     allowed.append(chat_id)
   except RuntimeError:pass
  if len(allowed)!=1:
   base.update({'status':'PRIVATE_CARD_SAFE_STOP','reason':'PRIVATE_MODERATOR_CHAT_NOT_UNIQUELY_VERIFIED',
                'matching_private_chats':len(allowed)})
   return base
  chat_id=allowed[0]
  # Dummy id cannot coincide with any already-existing poll.  It is not saved as a candidate.
  ident='QA'+uuid.uuid4().hex[:24]
  body=('🧪 ТЕСТ МОДЕРАЦІЇ · РАША ГУДБАЙ\n\n'
    'Це приватна перевірка кнопок бота. НЕ публікація опитування.\n'
    'Тестовий запис відсутній у черзі, тому натискання не повинно нічого опублікувати.\n\n'
    'Натисніть одну кнопку, а потім повідомте результат у чаті ChatGPT.')
  buttons={'inline_keyboard':[
   [{'text':'✅ ТЕСТ ПУБЛІКАЦІЇ','callback_data':'rp1:pub:'+ident}],
   [{'text':'🔄 ТЕСТ ПЕРЕРОБКИ','callback_data':'rp1:redo:'+ident}],
   [{'text':'❌ ТЕСТ ВІДХИЛЕННЯ','callback_data':'rp1:reject:'+ident}]]}
  # Pre-send claim prevents repeated sends on uncertainty. Never retry after failed/unknown sendMessage.
  claim={'status':'SEND_ATTEMPTED_NO_RETRY','time':int(time.time()),
         'chat_id_last4':str(chat_id)[-4:],'synthetic_id':ident}
  raw=json.dumps(claim,ensure_ascii=False,indent=2).encode('utf8')
  f=os.open(str(RECEIPT),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(f,'wb') as o:o.write(raw);o.flush();os.fsync(o.fileno())
  try:
   msg=api(token,'sendMessage',{'chat_id':chat_id,'text':body,'reply_markup':buttons})
   require(int(msg.get('chat',{}).get('id',0))==chat_id and msg.get('message_id'),
           'PRIVATE_SEND_RECEIPT_UNEXPECTED')
  except Exception as e:
   base.update({'status':'PRIVATE_SEND_UNCERTAIN_NO_RETRY','reason':str(e)[:120]})
   return base
  claim['status']='SENT_PRIVATE';claim['message_id']=msg['message_id']
  tmp=RECEIPT.with_name('.private_pilot_receipt_tmp')
  with open(tmp,'w',encoding='utf8') as o:
   os.chmod(tmp,0o600);json.dump(claim,o,ensure_ascii=False,indent=2);o.flush();os.fsync(o.fileno())
  os.replace(tmp,RECEIPT)
  base.update({'status':'ONE_PRIVATE_TEST_CARD_SENT','private_message_id':msg['message_id'],
               'chat_id_last4':str(chat_id)[-4:],
               'telegram_private_send_calls':1})
  return base
 finally:os.close(fd)
if __name__=='__main__':
 try:print(json.dumps(main(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_NEWS2_PRIVATE_PILOT_SAFE_STOP','reason':str(e)[:160],
    'publications':0,'new_pollers':0},ensure_ascii=False));sys.exit(2)
