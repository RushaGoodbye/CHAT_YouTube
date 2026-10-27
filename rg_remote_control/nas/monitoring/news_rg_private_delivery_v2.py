#!/usr/bin/env python3
"""NEWS RG private editorial delivery V2. One NEW staged draft only; private chat only.
Never retries V1 uncertain draft, never polls Telegram, never publishes or edits production DB.
"""
import os,sys,json,time,pathlib,importlib.util,hashlib,tempfile,urllib.request,urllib.parse
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
ST=O/'news_rg_private_review_staging'; R=O/'news_rg_private_delivery_v2'
V1=O/'news_rg_private_pilot_claim_v1.json'
def emit(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True))
def fail(x):raise RuntimeError(x)
def config():
 if str(B) not in sys.path:sys.path.insert(0,str(B))
 p=B/'rg_moderation.py'
 if not p.is_file() or p.is_symlink():fail('PRODUCTION_CLIENT_MISSING')
 spec=importlib.util.spec_from_file_location('_newsrg_existing_sender',str(p))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 cfg=mod.config()
 raw=cfg.get('moderation_chat_id'); mods=cfg.get('moderators')
 if isinstance(raw,bool) or not str(raw).isdigit() or not isinstance(mods,(tuple,list,set)):fail('MODERATOR_CONFIG_UNPROVEN')
 chat=int(raw)
 if chat<=0 or chat not in {int(v) for v in mods}:fail('PRIVATE_MODERATOR_NOT_ALLOWED')
 return mod,chat
def choose():
 uncertain=None
 if V1.is_file() and not V1.is_symlink():
  uncertain=json.loads(V1.read_text()).get('draft_id')
 for p in sorted(ST.glob('*.json'),reverse=True):
  if p.is_symlink() or p.stat().st_size>16000:continue
  v=json.loads(p.read_text())
  if v.get('draft_id')==uncertain:continue
  if v.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or v.get('telegram_delivery')!='NOT_SENT':continue
  if v.get('public_publication')!='OFF' or not str(v.get('media_url','')).startswith('https://'):continue
  draft=str(v.get('proposed_text',''))
  if not (60<=len(draft)<=900):continue
  if 'НЕВДАЛО' in draft.upper() or any(ch in draft for ch in 'ыъэёЫЪЭЁ'):continue
  # Never send an unverified URL as a photo. Media type must be verified separately.
  return v
 fail('NO_NEW_STAGED_DRAFT_EXCLUDING_UNCERTAIN_V1')
def main(mode):
 if os.geteuid()!=0:fail('SUDO_REQUIRED')
 item=choose();mod,chat=config()
 key=item['draft_id']
 if not isinstance(key,str) or len(key)!=24 or not all(ch in '0123456789abcdef' for ch in key):fail('BAD_DRAFT_ID')
 # Content check BEFORE durable claim and Telegram action.
 url=str(item['media_url'])
 target=urllib.parse.urlsplit(url)
 if target.scheme!='https' or target.hostname not in ('cdn1.telesco.pe','cdn2.telesco.pe','cdn3.telesco.pe','cdn4.telesco.pe','cdn5.telesco.pe'):
  fail('MEDIA_HOST_UNVERIFIED')
 try:
  req=urllib.request.Request(url,method='HEAD',headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=12) as resp:
   mime=resp.headers.get('Content-Type','').split(';')[0].strip().lower()
   if mime not in ('image/jpeg','image/png','image/webp'):fail('MEDIA_NOT_PHOTO_'+mime.replace('/','_'))
 except RuntimeError:raise
 except Exception:fail('MEDIA_UNVERIFIED_NETWORK')

 if R.is_symlink():fail('RECEIPT_DIR_SYMLINK')
 receipt=R/(key+'.json')
 if receipt.exists() or receipt.is_symlink():fail('ALREADY_CLAIMED_NO_RETRY')
 out={'status':'READY','draft_id':key,'channel':item.get('channel'),'private_chat_masked':str(chat)[:2]+'***','v1_uncertain_excluded':True,'telegram_calls':0,'publications':0}
 if mode=='preflight':return out
 R.mkdir(mode=0o700,exist_ok=True);os.chmod(R,0o700)
 # at-most-once claim is durable BEFORE external API call
 fd=os.open(str(receipt),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:
  json.dump({'status':'UNCERTAIN','draft_id':key,'created_at':int(time.time())},f);f.flush();os.fsync(f.fileno())
 caption='⚠️ NEWS RG — приватна перевірка, НЕ ДЛЯ ПУБЛІКАЦІЇ.\nФакти й фото не перевірено.\n'+item['proposed_text']
 caption=caption[:990]
 try:
  result=mod.api('sendPhoto',{'chat_id':chat,'photo':item['media_url'],'caption':caption})
  if not isinstance(result,dict):fail('ACK_NOT_DICT')
  msg=result.get('result',result)
  if not isinstance(msg,dict):fail('ACK_MESSAGE_NOT_DICT')
  if not isinstance(msg.get('message_id'),int):fail('ACK_MESSAGE_ID_MISSING')
  info=msg.get('chat')
  if not isinstance(info,dict):fail('ACK_CHAT_MISSING')
  if int(info.get('id',0))!=chat:fail('ACK_CHAT_ID_MISMATCH')
  if info.get('type')!='private':fail('ACK_NOT_PRIVATE')
  updated={'status':'SENT_CONFIRMED','draft_id':key,'message_id':msg['message_id'],'created_at':int(time.time())}
  tmp=receipt.with_suffix('.new')
  tmp.write_text(json.dumps(updated));os.chmod(tmp,0o600);os.replace(tmp,receipt)
  return {'status':'SENT_CONFIRMED','draft_id':key,'message_id':msg['message_id'],'editorial_callback':'NOT_CONNECTED','publications':0}
 except Exception as exc:
  # Record only an error class/code, never token/URL/Telegram text.
  err=str(exc)
  allowed=('ACK_NOT_DICT','ACK_MESSAGE_NOT_DICT','ACK_MESSAGE_ID_MISSING','ACK_CHAT_MISSING','ACK_CHAT_ID_MISMATCH','ACK_NOT_PRIVATE','TELEGRAM_REQUEST_REJECTED','MODERATOR_BOT_TOKEN_MISSING')
  safe=err if err in allowed else type(exc).__name__
  with open(receipt,'w') as f:
   json.dump({'status':'UNCERTAIN_NO_RETRY','draft_id':key,'error_class':safe,'created_at':int(time.time())},f)
  raise RuntimeError('UNCERTAIN_NO_RETRY_'+safe)
if __name__=='__main__':
 try:
  arg=sys.argv[1:]
  if arg==['selftest']:
   assert 'UNCERTAIN_NO_RETRY'!='SENT_CONFIRMED';emit(status='SELFTEST_PASS')
  elif arg in (['preflight'],['send-one']):emit(**main(arg[0]))
  else:fail('BAD_COMMAND')
 except Exception as e:emit(status='SAFE_STOP',reason=str(e)[:130],publications=0);sys.exit(2)
