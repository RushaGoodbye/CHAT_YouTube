#!/usr/bin/env python3
"""RG News2 P36: send exactly ONE private acknowledgement for a previously archived
test-button click. This does not replay updates, process real decisions,
advance Telegram offset, touch cron, or publish any news.
"""
import datetime,json,os,pathlib,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
ARCHIVE=O/'updates_handoff_guarded_20261024T135202473388Z.json'
MARK=O/'p36_ack_615861399.json'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
BOT_ID=7492268627
def output(**x): print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def write_mark(status,detail):
 p=MARK
 # write marker by truncating a file this process created only.
 with p.open('w',encoding='utf-8') as f:
  json.dump({'status':status,'detail':detail,
   'updated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},f,
   ensure_ascii=False)
  f.flush();os.fsync(f.fileno())
 os.chmod(p,0o600)
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink() or ARCHIVE.is_symlink():raise RuntimeError('UNSAFE_ARCHIVE_DIR')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_GATE_PRESENT')
 if (B/'PUBLISH_ENABLED').exists():raise RuntimeError('PUBLICATION_GATE_MUST_BE_OFF')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('OWNER_GATE_CHANGED')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('MODERATION_GATE_MISSING')
 if MARK.exists() or MARK.is_symlink():
  try:
   old=json.loads(MARK.read_text('utf-8'))
   status=old.get('status')
  except Exception:status='UNKNOWN'
  output(status='P36_ALREADY_ATTEMPTED_NO_DUPLICATE',previous_status=status,
    publication_sends=0,telegram_polls=0)
  return
 if not ARCHIVE.is_file():raise RuntimeError('ARCHIVED_TEST_EVENT_MISSING')
 obj=json.loads(ARCHIVE.read_text('utf-8'))
 hits=[u for u in obj.get('updates',[]) if isinstance(u,dict) and u.get('update_id')==615861399]
 if len(hits)!=1:raise RuntimeError('TEST_UPDATE_ID_NOT_UNIQUE')
 event=hits[0];q=event.get('callback_query') or {};m=q.get('message') or {}
 actor=q.get('from') or {};chat=m.get('chat') or {}
 data=str(q.get('data',''))
 if not (data.startswith('rgprobe25:') and len(data.split(':'))==2
   and len(data.split(':')[1])==18 and
   all(ch in '0123456789abcdef' for ch in data.split(':')[1])
   and m.get('message_id')==8032 and
   chat.get('type')=='private' and
   actor.get('is_bot') is False and
   (m.get('from') or {}).get('username')=='RushaGoodbyeNews_bot'):
  raise RuntimeError('ARCHIVED_TEST_AUTHENTICITY_FAILED')
 sys.path.insert(0,str(B))
 import rg_moderation as mod
 cfg=mod.config()
 recipient=int(cfg['moderation_chat_id'])
 if (recipient<=0 or recipient not in cfg['moderators'] or
     chat.get('id')!=recipient or actor.get('id')!=recipient):
  raise RuntimeError('AUTHORIZED_PRIVATE_CHAT_MISMATCH')
 who=mod.api('getMe',{})
 if who.get('id')!=BOT_ID or who.get('username')!='RushaGoodbyeNews_bot':
  raise RuntimeError('WRONG_BOT')
 # An exclusive marker is written BEFORE any send to avoid accidental duplicate
 # notifications if the connection fails after Telegram accepts the message.
 with os.fdopen(os.open(str(MARK),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  json.dump({'status':'PENDING_SEND','update_id':615861399,
     'reply_to_message_id':8032},f)
  f.flush();os.fsync(f.fileno())
 try:
  response=mod.api('sendMessage',{'chat_id':recipient,'reply_to_message_id':8032,
   'text':'✅ RG NEWS 2.0: підтвердження раніше отриманого тестового натискання. NAS отримав кнопку 8032. Це одноразова перевірка відповіді бота; публікація новин вимкнена.'})
  if not isinstance(response,dict) or not isinstance(response.get('message_id'),int):
   write_mark('DELIVERY_UNCERTAIN','NO_VALID_MESSAGE_ID')
   output(status='P36_PRIVATE_REPLY_UNCERTAIN',publication_sends=0,telegram_polls=0)
   return
  write_mark('PRIVATE_REPLY_CONFIRMED',str(response['message_id']))
  output(status='P36_PRIVATE_REPLY_CONFIRMED',
    reply_to_test_message_id=8032,confirmation_message_id=response['message_id'],
    source_update_id=615861399,publication_sends=0,
    telegram_polls=0,offset_changes=0,cron_changes=0)
 except Exception as exc:
  write_mark('DELIVERY_UNCERTAIN',type(exc).__name__)
  output(status='P36_PRIVATE_REPLY_UNCERTAIN',error_type=type(exc).__name__,
    publication_sends=0,telegram_polls=0,offset_changes=0)
if __name__=='__main__':
 try:main()
 except Exception as exc:
  output(status='P36_BLOCKED',
    reason=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,
    publication_sends=0,telegram_polls=0)
  sys.exit(1)
