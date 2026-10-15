#!/usr/bin/env python3
"""RG News2 controlled callback handoff: explicitly authorized ONE-SHOT.
No persistent owner marker, no cron changes, no channel publication.
Archives all returned updates BEFORE advancing the offset.
"""
import fcntl,json,os,pathlib,sys,tempfile,datetime
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
LEG=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
def emit(**d): print(json.dumps(d,ensure_ascii=False,sort_keys=True),flush=True)
def main():
 if len(sys.argv)!=2 or sys.argv[1]!='once':raise RuntimeError('USAGE_ONCE_ONLY')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if LEG.exists() or LEG.is_symlink():raise RuntimeError('LEGACY_BOT_MAY_POLL')
 if (BASE/'PUBLISH_ENABLED').exists():raise RuntimeError('PUBLICATION_MUST_BE_OFF')
 if not (BASE/'MODERATION_DELIVERY_ENABLED').is_file():raise RuntimeError('DELIVERY_NOT_READY')
 if (BASE/'NAS_EXCLUSIVE_OWNER_VERIFIED').exists():raise RuntimeError('ALREADY_OWNED_USE_NORMAL_RUNNER')
 directory=BASE/'operator'
 if directory.is_symlink():raise RuntimeError('UNSAFE_OPERATOR_DIR')
 directory.mkdir(mode=0o700,exist_ok=True)
 fd=os.open(str(directory/'controlled_handoff.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except (IOError,OSError):raise RuntimeError('ANOTHER_HANDOFF_RUNNING')
 sys.path.insert(0,str(BASE))
 import rg_moderation as m
 cfg=m.config()
 if cfg['moderation_chat_id']<=0 or cfg['moderation_chat_id'] not in cfg['moderators']:
  raise RuntimeError('PERSONAL_MODERATOR_ONLY')
 webhook=m.api('getWebhookInfo',{})
 if webhook.get('url'):raise RuntimeError('WEBHOOK_ACTIVE_NO_POLL')
 with m.db_connect() as db:
  row=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  offset=int(row['value']) if row else 0
 # A conflict (Telegram 409) must abort without advancing offset.
 updates=m.api('getUpdates',{'offset':offset,'limit':100,'timeout':0,'allowed_updates':['callback_query']})
 if not isinstance(updates,list):raise RuntimeError('BAD_TELEGRAM_UPDATES')
 if not all(isinstance(u,dict) and isinstance(u.get('update_id'),int) for u in updates):
  raise RuntimeError('BAD_UPDATE_IDS')
 # Preserve every update, including ignored messages, before any acknowledgements.
 timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 archive=directory/('updates_handoff_'+timestamp+'.json')
 raw=json.dumps({'input_offset':offset,'updates':updates},ensure_ascii=False).encode('utf-8')
 with os.fdopen(os.open(str(archive),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:
  f.write(raw);f.flush();os.fsync(f.fileno())
 outcomes=[]
 max_offset=offset
 for u in updates:
  # Do not process unknown kinds. Keep them in the durable archive.
  if 'callback_query' in u:
   result=m.process_callback(u,cfg)
   outcomes.append(result.get('status','UNKNOWN'))
   q=u.get('callback_query') or {}
   if q.get('id'):
    try:m.api('answerCallbackQuery',{'callback_query_id':q['id'],'text':result.get('status','')[:180]})
    except Exception:pass
  else:outcomes.append('ARCHIVED_NON_CALLBACK')
  next_offset=u['update_id']+1
  if next_offset>max_offset:
   max_offset=next_offset
   with m.db_connect() as db:
    db.execute("INSERT OR REPLACE INTO moderation_meta(key,value) VALUES('offset',?)",(str(max_offset),))
 emit(status='ONE_SHOT_CALLBACK_HANDOFF_COMPLETE',update_count=len(updates),outcomes=outcomes,
  archive=str(archive),offset_before=offset,offset_after=max_offset,
  publication_gate_opened=False,owner_gate_opened=False,scheduler_changed=False,channel_sends=0,
  exclusive_owner_proven=False,next='Do not enable unattended polling until ownership is independently resolved.')
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,channel_sends=0)
  sys.exit(1)
