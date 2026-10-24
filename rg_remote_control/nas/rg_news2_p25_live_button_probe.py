#!/usr/bin/env python3
"""RG Telegram News2 P25. Single foreground end-to-end private test-button probe.
No background job, no ownership markers, no publication; archive before offset.
"""
import datetime,fcntl,json,os,pathlib,secrets,sys,time
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
BOT_ID=7492268627
def emit(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True),flush=True)
def stamp():return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
def archive(offset,updates):
 p=OP/('p25_updates_'+stamp()+'.json')
 with os.fdopen(os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  json.dump({'offset':offset,'updates':updates},f,ensure_ascii=False)
  f.flush();os.fsync(f.fileno())
 return p.name
def gates():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not OP.is_dir() or OP.is_symlink():raise RuntimeError('UNSAFE_OPERATOR_DIR')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_GATE_ACTIVE')
 if (BASE/'PUBLISH_ENABLED').exists():raise RuntimeError('CHANNEL_PUBLICATION_GATE_OPEN')
 if (BASE/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('OWNERSHIP_MODE_CHANGED')
 if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('MODERATION_GATE_CLOSED')
 sys.path.insert(0,str(BASE))
 import rg_moderation as m
 cfg=m.config(); chat=int(cfg['moderation_chat_id'])
 if chat<=0 or chat not in cfg['moderators']:raise RuntimeError('AUTHORIZED_PERSONAL_CHAT_REQUIRED')
 info=m.api('getMe',{})
 if info.get('id')!=BOT_ID or info.get('username')!='RushaGoodbyeNews_bot':
  raise RuntimeError('BOT_IDENTITY_DIFFERENT')
 hook=m.api('getWebhookInfo',{})
 if hook.get('url'):raise RuntimeError('WEBHOOK_ACTIVE_NO_POLL')
 return m,cfg,chat
def db_offset(m):
 with m.db_connect() as db:
  r=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  return int(r['value']) if r else 0
def save_offset(m,offset):
 with m.db_connect() as db:
  db.execute("INSERT OR REPLACE INTO moderation_meta(key,value) VALUES('offset',?)",(str(offset),))
def main():
 m,cfg,chat=gates()
 fd=os.open(str(OP/'controlled_handoff.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):raise RuntimeError('CALLBACK_HANDLER_ALREADY_RUNNING')
  nonce=secrets.token_hex(9); data='rgprobe25:'+nonce
  payload={'chat_id':chat,
   'text':'🧪 RG NEWS 2.0 — ПРОВЕРКА КНОПКИ\nНажмите кнопку ниже в этом личном чате. Публикация новостей отключена.',
   'reply_markup':{'inline_keyboard':[[{'text':'🧪 Проверить кнопку','callback_data':data}]]}}
  # Only private moderator destination, never a channel or a candidate.
  msg=m.api('sendMessage',payload)
  if not isinstance(msg,dict) or not isinstance(msg.get('message_id'),int):
   raise RuntimeError('TEST_CARD_SEND_UNCERTAIN_CHECK_BOT_BEFORE_RETRY')
  mid=msg['message_id']
  off=db_offset(m)
  emit(status='P25_TEST_SENT_CLICK_BUTTON_NOW',bot='RushaGoodbyeNews_bot',message_id=mid,
       channel_sends=0,publication_gate_opened=False,timeout_seconds=70)
  deadline=time.monotonic()+70;rounds=0;received=0;handled_real=0
  while time.monotonic()<deadline:
   rounds+=1
   try:
    ups=m.api('getUpdates',{'offset':off,'limit':100,'timeout':0,'allowed_updates':['callback_query']})
   except Exception as ex:
    emit(status='P25_POLL_ERROR',error_type=type(ex).__name__,round=rounds,
      test_message_id=mid,channel_sends=0)
    return
   if not isinstance(ups,list) or any(not isinstance(u,dict) or not isinstance(u.get('update_id'),int) for u in ups):
    raise RuntimeError('UNEXPECTED_UPDATES_FORMAT')
   if ups:
    aname=archive(off,ups)
    for u in ups:
     q=u.get('callback_query') if isinstance(u.get('callback_query'),dict) else None
     if q is not None:
      qm=q.get('message') or {};user=q.get('from') or {};c=qm.get('chat') or {}
      match=(q.get('data')==data and qm.get('message_id')==mid and
         c.get('id')==chat and user.get('id')==chat)
      if match:
       # Durable archive exists before ack, answer only test callback.
       try:
        if q.get('id'):m.api('answerCallbackQuery',{'callback_query_id':q['id'],'text':'✅ Тест пройден'})
       except Exception:pass
       save_offset(m,u['update_id']+1)
       emit(status='P25_BUTTON_CONFIRMED',test_message_id=mid,update_id=u['update_id'],
          received=received+1,other_callbacks_handled=handled_real,
          archive=aname,channel_sends=0,exclusive_owner_proven=False)
       return
      # Never discard unrelated live user moderation decisions.
      result=m.process_callback(u,cfg)
      handled_real+=1
      if q.get('id'):
       try:m.api('answerCallbackQuery',{'callback_query_id':q['id'],'text':str(result.get('status',''))[:120]})
       except Exception:pass
     nextoff=u['update_id']+1
     if nextoff>off:
      save_offset(m,nextoff);off=nextoff
     received+=1
   time.sleep(2)
  emit(status='P25_TEST_CALLBACK_NOT_RECEIVED',test_message_id=mid,rounds=rounds,
       received_other_updates=received,handled_real_callbacks=handled_real,
       saved_offset=off,channel_sends=0,exclusive_owner_proven=False,
       interpretation='Could be competing consumer, no button press, or Telegram delivery issue')
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='P25_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
       channel_sends=0)
  sys.exit(1)
