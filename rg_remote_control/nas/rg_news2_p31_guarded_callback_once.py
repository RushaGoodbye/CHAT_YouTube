#!/usr/bin/env python3
"""News2 guarded probation callback tick.
Explicitly NO publish/approve processing. Never sends outside private moderator.
Archive-before-ack. One run only; external probation cron controls cadence.
"""
import datetime,fcntl,json,os,pathlib,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
ACTIONS={'reject','recheck','similar'}
BOT_ID=7492268627
def emit(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def stamp():return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
def guards():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('OPERATOR_UNSAFE')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_BOT_GATE_OPEN')
 if (B/'PUBLISH_ENABLED').exists():raise RuntimeError('CHANNEL_PUBLISH_GATE_OPEN')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('EXCLUSIVE_OWNER_FLAG_SET')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_DISABLED')
 sys.path.insert(0,str(B))
 import rg_moderation as m
 cfg=m.config()
 chat=int(cfg['moderation_chat_id'])
 if chat<=0 or chat not in cfg['moderators']:raise RuntimeError('PRIVATE_MODERATOR_INVALID')
 if (m.api('getMe',{}).get('id')!=BOT_ID):raise RuntimeError('BOT_ID_MISMATCH')
 if m.api('getWebhookInfo',{}).get('url'):raise RuntimeError('ACTIVE_WEBHOOK')
 return m,cfg,chat
def getoff(m):
 with m.db_connect() as db:
  r=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  return int(r['value']) if r else 0
def putoff(m,off):
 with m.db_connect() as db:
  db.execute("INSERT OR REPLACE INTO moderation_meta(key,value) VALUES('offset',?)",(str(off),))
def archive(off,ups):
 p=O/('updates_handoff_guarded_'+stamp()+'.json')
 raw=json.dumps({'input_offset':off,'updates':ups},ensure_ascii=False).encode('utf-8')
 with os.fdopen(os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
  f.write(raw);f.flush();os.fsync(f.fileno())
 return p.name
def main():
 if len(sys.argv)!=2 or sys.argv[1]!='once':raise RuntimeError('USAGE_ONCE_ONLY')
 m,cfg,chat=guards()
 fd=os.open(str(O/'controlled_handoff.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (OSError,BlockingIOError):raise RuntimeError('CALLBACK_LOCK_BUSY')
  off=getoff(m)
  ups=m.api('getUpdates',{'offset':off,'limit':100,'timeout':0,'allowed_updates':['callback_query']})
  if not isinstance(ups,list) or any(not isinstance(u,dict) or not isinstance(u.get('update_id'),int) for u in ups):
   raise RuntimeError('BAD_UPDATE_RESPONSE')
  filename=archive(off,ups)
  # Unknown callback families may belong to another system sharing the bot.
  # Do not acknowledge or steal them. Pause probation pending investigation.
  for item in ups:
   query=item.get('callback_query')
   if not isinstance(query,dict):continue
   val=str(query.get('data',''))
   if not (val.startswith('rg3:') or val.startswith('rgprobe25:')):
    raise RuntimeError('FOREIGN_CALLBACK_FAMILY_DETECTED_NOT_ACKNOWLEDGED')
  old_api=m.api
  def api_guard(method,payload):
   # Callback answers, edits and sends may target ONLY the authorized moderator chat.
   # All other Telegram send endpoints are denied; reading endpoints allowed.
   act=str(method).lower()
   if any(act.startswith(t) for t in ('send','copy','forward','edit','delete','pin','unpin','ban','restrict','kick','approvechatjoin','declinechatjoin')):
    cid=payload.get('chat_id') if isinstance(payload,dict) else None
    if cid is None or str(cid)!=str(chat):
     raise RuntimeError('OUTBOUND_TO_NON_MODERATOR_BLOCKED')
   return old_api(method,payload)
  m.api=api_guard
  statuses=[]; ui_results=[]
  def dispatch_state(message_id):
   if not isinstance(message_id,int):return None
   with m.db_connect() as db:
    rec=db.execute("""SELECT c.id,c.status FROM moderation_dispatch d
       JOIN candidates c ON d.candidate_id=c.id
       WHERE d.message_id=? LIMIT 1""",
       (message_id,)).fetchone()
    return (str(rec[0]),str(rec[1])) if rec else None
  for u in ups:
   q=u.get('callback_query') or {}
   if isinstance(q,dict) and q:
    parts=str(q.get('data','')).split(':')
    message=q.get('message') or {}
    actor=q.get('from') or {}
    mch=message.get('chat') or {}
    owned=(parts[0]=='rg3' and len(parts)>=3 and actor.get('id')==chat
      and mch.get('id')==chat and mch.get('type')=='private')
    is_test=(len(parts)==2 and parts[0]=='rgprobe25'
      and len(parts[1])==18 and all(ch in '0123456789abcdef' for ch in parts[1])
      and actor.get('id')==chat and mch.get('id')==chat
      and mch.get('type')=='private' and message.get('message_id') in (8031,8032))
    if is_test:
     mid=message['message_id']
     note={'message_id':mid,'kind':'TEST_BUTTON','confirmation_sent':False}
     try:
      m.api('sendMessage',{'chat_id':chat,'reply_to_message_id':mid,
        'text':'✅ RG NEWS 2.0: тестова кнопка працює. Натискання отримано NAS, публікація новин вимкнена.'})
      note['confirmation_sent']=True
      status='TEST_BUTTON_VISIBLE_CONFIRMATION_SENT'
     except Exception as error:
      note['error_type']=type(error).__name__
      status='TEST_BUTTON_VISIBLE_CONFIRMATION_FAILED'
     ui_results.append(note)
    elif owned and parts[1] in ACTIONS:
     mid=message.get('message_id')
     before=dispatch_state(mid)
     ret=m.process_callback(u,cfg)
     status=str(ret.get('status','UNKNOWN'))[:90]
     after=dispatch_state(mid)
     if (before and after and before[0]==after[0] and before[1]!=after[1]):
      # Make a confirmed database transition visible on the exact moderator card.
      change={'message_id':mid,'action':parts[1],
              'before':before[1],'after':after[1],
              'reply_markup_cleared':False,'confirmation_sent':False}
      try:
       m.api('editMessageReplyMarkup',{
        'chat_id':chat,'message_id':mid,
        'reply_markup':{'inline_keyboard':[]}})
       change['reply_markup_cleared']=True
      except Exception as error:
       change['ui_error_type']=type(error).__name__
      # Message stays in the same private moderator chat; no news-channel sends.
      labels={'recheck':'🔄 Новину направлено на переперевірку',
              'reject':'❌ Новину відхилено',
              'similar':'🔎 Перевірку схожих новин виконано'}
      try:
       m.api('sendMessage',{'chat_id':chat,'reply_to_message_id':mid,
        'text':labels.get(parts[1],'✅ Рішення оброблено')})
       change['confirmation_sent']=True
      except Exception as error:
       change['confirmation_error_type']=type(error).__name__
      ui_results.append(change)
    elif owned and parts[1]=='approve':
     status='APPROVAL_PAUSED_PUBLISH_DISABLED'
    else:
     status='UNRECOGNIZED_OR_TEST_CALLBACK_ARCHIVED'
    if q.get('id'):
     try:
      old_api('answerCallbackQuery',{
       'callback_query_id':q['id'],
       'text':('✅ Кнопка працює, підтвердження в чаті.' if status=='TEST_BUTTON_VISIBLE_CONFIRMATION_SENT'
        else '⚠️ Не вдалося надіслати відповідь; див. журнал.' if status=='TEST_BUTTON_VISIBLE_CONFIRMATION_FAILED'
        else '⚠️ Публікацію тимчасово вимкнено; дію не виконано.' if status=='APPROVAL_PAUSED_PUBLISH_DISABLED'
        else 'Оброблено' if owned and parts[1] in ACTIONS else 'Кнопка не активна')})
     except Exception:pass
    statuses.append(status)
   else:statuses.append('NON_CALLBACK_ARCHIVED')
   off=max(off,u['update_id']+1)
   putoff(m,off)
  emit(status='ONE_SHOT_CALLBACK_HANDOFF_COMPLETE',update_count=len(ups),
   outcomes=statuses,ui_results=ui_results,offset_after=off,archive_name=filename,
   publication_gate_opened=False,channel_sends=0,
   approval_callbacks_executed=0,exclusive_owner_proven=False)
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   channel_sends=0);sys.exit(1)
