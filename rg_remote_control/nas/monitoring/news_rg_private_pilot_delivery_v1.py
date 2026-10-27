#!/usr/bin/env python3
"""NEWS RG: one private AI draft delivery through existing rg_moderation API.
Private-only pilot. Never polls callbacks, writes production SQLite, or publishes.
At-most-once claim is durable. No auto retries on uncertain result.
"""
import sys,os,json,pathlib,hashlib,importlib.util,datetime,time,stat
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2'); O=B/'operator'
ST=O/'news_rg_private_review_staging';LOG=O/'news_rg_private_pilot_claim_v1.json'
RG=B/'rg_moderation.py'
def emit(x):print(json.dumps(x,ensure_ascii=False,sort_keys=True))
def safe():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 for p in (RG,ST):
  if not p.exists() or p.is_symlink():raise RuntimeError('UNSAFE_PATH_'+p.name)
 files=sorted(ST.glob('*.json'))
 if not files:raise RuntimeError('NO_STAGED_DRAFT')
 p=files[-1]
 if p.is_symlink() or p.stat().st_size>16000:raise RuntimeError('DRAFT_UNSAFE')
 o=json.loads(p.read_text())
 if o.get('schema')!='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1' or o.get('telegram_delivery')!='NOT_SENT' or o.get('public_publication')!='OFF':raise RuntimeError('BAD_STAGING_CONTRACT')
 if not str(o.get('media_url','')).startswith('https://'):raise RuntimeError('NO_HTTPS_MEDIA')
 return p,o
def resolve():
 if str(B) not in sys.path:sys.path.insert(0,str(B))
 spec=importlib.util.spec_from_file_location('_rg_production_moderation_readonly',str(RG))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 if not callable(getattr(module,'config',None)) or not callable(getattr(module,'api',None)):raise RuntimeError('EXISTING_SENDER_UNAVAILABLE')
 cfg=module.config()
 if not isinstance(cfg,dict):raise RuntimeError('EXISTING_CONFIG_UNEXPECTED')
 # Existing config must unambiguously expose a dedicated private moderator ID.
 vals=[(k,int(v)) for k,v in cfg.items() if ('moderator' in str(k).lower() or 'admin_chat' in str(k).lower()) and ('chat' in str(k).lower() or str(k).lower()=='moderator_id') and str(v).lstrip('-').isdigit()]
 uniq={v for _,v in vals if v>0}
 if len(uniq)!=1:
  keys=[str(k) for k in cfg.keys() if not any(word in str(k).lower() for word in ('token','password','secret','key','auth','url'))]
  raise RuntimeError('PRIVATE_MODERATOR_CHAT_NOT_PROVEN_CONFIG_KEYS_'+','.join(keys)[:220])
 chat=next(iter(uniq))
 return module,chat
def do(preflight):
 p,item=safe()
 module,chat=resolve()
 out={'status':'PREFLIGHT_READY','private_chat_id_masked':str(chat)[:2]+'***',
      'source_channel':item.get('channel'),'telegram_calls':0,'publications':0,
      'callback_buttons':'NOT_INSTALLED','production_db_writes':0}
 if preflight:return out
 if LOG.exists() or LOG.is_symlink():raise RuntimeError('PILOT_PREVIOUSLY_CLAIMED_NO_RETRY')
 # Hard stop if already previously delivered; no second message.
 txt=str(item['proposed_text']).strip()
 if not 50<=len(txt)<=900:raise RuntimeError('DRAFT_CAPTION_NOT_READY')
 caption=('⚠️ NEWS RG — приватний тест редакційної черги.\n'
          'НЕ ПЕРЕВІРЕНО: потрібна перевірка фактів і фото.\n'
          +txt)[:990]
 # Exclusive claim before uncertain external API call.
 fd=os.open(str(LOG),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:
  json.dump({'status':'SENDING_UNCERTAIN','draft_id':item['draft_id'],'created_at':int(time.time()),'publications':0},f)
  f.flush();os.fsync(f.fileno())
 try:
  response=module.api('sendPhoto',{'chat_id':chat,'photo':item['media_url'],'caption':caption})
  if not isinstance(response,dict):raise RuntimeError('API_RESPONSE_UNEXPECTED')
  msg=response.get('result',response)
  if not isinstance(msg,dict) or not isinstance(msg.get('message_id'),int) or msg.get('chat',{}).get('id')!=chat:raise RuntimeError('ACK_NOT_PROVEN')
  # Updating receipt is informational; never retry upon failure.
  tmp=LOG.with_suffix('.json.tmp')
  tmp.write_text(json.dumps({'status':'PRIVATE_PHOTO_SENT_CONFIRMED','draft_id':item['draft_id'],'message_id':msg['message_id'],'created_at':int(time.time())}))
  os.chmod(tmp,0o600);os.replace(tmp,LOG)
  return {'status':'PRIVATE_PHOTO_SENT_CONFIRMED','draft_id':item['draft_id'],'message_id':msg['message_id'],'callback_buttons':'NOT_INSTALLED','publications':0}
 except Exception as e:
  raise RuntimeError('PILOT_UNCERTAIN_NO_AUTOMATIC_RETRY_'+type(e).__name__)
if __name__=='__main__':
 try:
  cmd=sys.argv[1:]
  if cmd==['selftest']:
   assert 'sendPhoto'!='getUpdates';emit({'status':'SELFTEST_PASS'})
  elif cmd==['preflight']:emit(do(True))
  elif cmd==['send-one']:emit(do(False))
  else:raise RuntimeError('BAD_MODE')
 except Exception as exc:emit({'status':'SAFE_STOP','reason':str(exc)[:150],'publications':0});sys.exit(2)
