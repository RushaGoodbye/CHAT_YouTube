#!/usr/bin/env python3
"""News2 outbound queue v2: count only cards with still-pending decisions.
One manual tick sends <=1 photo. No getUpdates, no crons, no channel publishing.
"""
import fcntl,json,os,pathlib,sys
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
LEGACY=pathlib.Path('/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled')
def emit(**kw):print(json.dumps(kw,ensure_ascii=False,sort_keys=True),flush=True)
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ('status','tick'):raise RuntimeError('USAGE_STATUS_OR_TICK')
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if LEGACY.exists() or LEGACY.is_symlink():raise RuntimeError('LEGACY_GATE_PRESENT')
 if (BASE/'PUBLISH_ENABLED').exists():raise RuntimeError('CHANNEL_PUBLICATION_GATE_OPEN')
 gate=BASE/'MODERATION_DELIVERY_ENABLED'
 if not gate.is_file() or gate.is_symlink():raise RuntimeError('DELIVERY_GATE_CLOSED')
 sys.path.insert(0,str(BASE))
 import rg_moderation as m
 cfg=m.config()
 if cfg['moderation_chat_id']<=0 or cfg['moderation_chat_id'] not in cfg['moderators']:
  raise RuntimeError('PERSONAL_MODERATOR_REQUIRED')
 lock_dir=BASE/'operator'
 if not lock_dir.is_dir() or lock_dir.is_symlink():raise RuntimeError('OPERATOR_DIRECTORY_MISSING')
 fd=os.open(str(lock_dir/'outbound_queue.lock'),os.O_CREAT|os.O_RDWR,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with m.db_connect() as db:
   rows=db.execute("""SELECT d.state,c.status,count(*) AS n FROM moderation_dispatch d
     JOIN candidates c ON c.id=d.candidate_id GROUP BY d.state,c.status""").fetchall()
   statuses=[{'dispatch_state':r['state'],'candidate_status':r['status'],'count':r['n']} for r in rows]
   pending=db.execute("""SELECT count(*) AS n FROM moderation_dispatch d
     JOIN candidates c ON c.id=d.candidate_id
     WHERE d.state IN ('sent','send_uncertain')
     AND c.status IN ('awaiting_moderation','awaiting_photo_review')""").fetchone()['n']
  if sys.argv[1]=='status':
   emit(status='QUEUE_V2_STATUS',pending=pending,limit=3,breakdown=statuses,telegram_polls=0,channel_sends=0)
   return
  if pending>=3:
   emit(status='QUEUE_AT_CAPACITY',pending=pending,limit=3,telegram_polls=0,channel_sends=0)
   return
  result=m.send_one()
  emit(status=result.get('status'),candidate_id=result.get('id'),message_id=result.get('message_id'),
   pending_before=pending,limit=3,telegram_polls=0,channel_sends=0)
 finally:os.close(fd)
if __name__=='__main__':
 try:main()
 except Exception as ex:
  emit(status='BLOCKED',reason=str(ex) if isinstance(ex,RuntimeError) else type(ex).__name__,channel_sends=0)
  sys.exit(1)
