#!/usr/bin/env python3
"""RG News2 P30: verify real reject callback in a 75-second foreground window.
Archives Telegram updates before ack; never publishes or changes channel gates.
Requires an existing pending review card and a real authorized moderator click.
"""
import datetime,fcntl,json,os,pathlib,sys,tempfile,time
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
PROOF=O/'p30_real_decision_proof.json'
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
def emit(**d):print(json.dumps(d,ensure_ascii=False,sort_keys=True),flush=True)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def stamp():return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
def writeproof(d):
 fd,tmp=tempfile.mkstemp(dir=str(O),prefix='.p30_proof_')
 try:
  with os.fdopen(fd,'w') as f:json.dump(d,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,0o600);os.replace(tmp,str(PROOF))
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def prereq():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not O.is_dir() or O.is_symlink():raise RuntimeError('UNSAFE_OPERATOR_DIR')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_CUTOVER_PRESENT')
 if (B/'PUBLISH_ENABLED').exists():raise RuntimeError('PUBLICATION_GATE_MUST_BE_CLOSED')
 if (B/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('OWNER_CUTOVER_MODE_CHANGED')
 if not (B/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_GATE_CLOSED')
 sys.path.insert(0,str(B))
 import rg_moderation as m
 cfg=m.config()
 chat=int(cfg['moderation_chat_id'])
 if chat<=0 or chat not in cfg['moderators']:raise RuntimeError('PERSONAL_MODERATOR_REQUIRED')
 hook=m.api('getWebhookInfo',{})
 if hook.get('url'):raise RuntimeError('WEBHOOK_PRESENT_NO_POLL')
 bot=m.api('getMe',{})
 if bot.get('id')!=7492268627:raise RuntimeError('WRONG_BOT_ID')
 return m,cfg,chat
def state(m,mid):
 with m.db_connect() as db:
  r=db.execute('SELECT c.status,d.state,c.id FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id WHERE d.message_id=? LIMIT 1',(mid,)).fetchone()
  return (str(r[0]),str(r[1]),str(r[2])) if r else None
def pending(m):
 with m.db_connect() as db:
  return [int(r[0]) for r in db.execute(
   "SELECT d.message_id FROM moderation_dispatch d JOIN candidates c ON c.id=d.candidate_id WHERE d.state='sent' AND c.status IN ('awaiting_photo_review','awaiting_moderation') ORDER BY d.message_id DESC LIMIT 8")]
def offset(m):
 with m.db_connect() as db:
  r=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  return int(r['value']) if r else 0
def saveoff(m,n):
 with m.db_connect() as db:
  db.execute("INSERT OR REPLACE INTO moderation_meta(key,value) VALUES('offset',?)",(str(n),))
def backup(off,updates):
 p=O/('p30_updates_'+stamp()+'.json')
 with os.fdopen(os.open(str(p),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
  json.dump({'input_offset':off,'updates':updates},f,ensure_ascii=False)
  f.flush();os.fsync(f.fileno())
 return p
def main():
 m,cfg,chat=prereq()
 fd=os.open(str(O/'controlled_handoff.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except (BlockingIOError,OSError):raise RuntimeError('ANOTHER_CALLBACK_HANDLER_RUNNING')
  ids=pending(m)
  if not ids:raise RuntimeError('NO_PENDING_REVIEW_CARD')
  emit(status='P30_READY_PRESS_REJECT_NOW',pending_card_message_ids=ids,
    instruction='Open a listed card and press REJECT while this command is running',
    channel_sends=0,timeout_seconds=75)
  off=offset(m);stop=time.monotonic()+75;found=None;updates_seen=0
  while time.monotonic()<stop:
   batch=m.api('getUpdates',{'offset':off,'limit':100,'timeout':0,'allowed_updates':['callback_query']})
   if not isinstance(batch,list) or any(not isinstance(u,dict) or not isinstance(u.get('update_id'),int) for u in batch):
    raise RuntimeError('TELEGRAM_BAD_UPDATE_PAYLOAD')
   if batch:
    file=backup(off,batch)
    for u in batch:
     q=u.get('callback_query')
     if isinstance(q,dict):
      data=str(q.get('data','')).split(':')
      msg=q.get('message') or {}
      origin=q.get('from') or {}
      chatdata=msg.get('chat') or {}
      mid=msg.get('message_id')
      is_target=(
       len(data)>=3 and data[0]=='rg3' and data[1]=='reject'
       and mid in ids and origin.get('id')==chat and chatdata.get('id')==chat
       and chatdata.get('type')=='private')
      before=state(m,mid) if is_target else None
      result=m.process_callback(u,cfg)
      if q.get('id'):
       try:m.api('answerCallbackQuery',{
        'callback_query_id':q['id'],
        'text':str(result.get('status',''))[:140]})
       except Exception:pass
      after=state(m,mid) if is_target else None
      if (is_target and before and after and
          before[0] in ('awaiting_photo_review','awaiting_moderation')
          and after[0] not in ('awaiting_photo_review','awaiting_moderation')
          and after[2]==before[2]):
       found={'verified':True,'message_id':mid,'update_id':u['update_id'],
        'candidate_id':after[2],'before':before[0],'after':after[0],
        'action':'reject','time_utc':utc(),'archive_name':file.name}
       writeproof(found)
     off=max(off,u['update_id']+1)
     saveoff(m,off)
     updates_seen+=1
     if found:
      emit(status='P30_REAL_REJECT_CONFIRMED',message_id=found['message_id'],
       update_id=found['update_id'],before=found['before'],after=found['after'],
       offset=off,archive_name=found['archive_name'],
       channel_sends=0,owner_exclusivity_proven=False)
      return
   time.sleep(2)
  emit(status='P30_NO_CONFIRMED_REJECT',updates_seen=updates_seen,
    pending_cards=ids,offset=off,channel_sends=0)
  raise RuntimeError('NO_REAL_REJECT_RECEIVED_WITHIN_75_SECONDS')
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='P30_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
   channel_sends=0);sys.exit(1)
