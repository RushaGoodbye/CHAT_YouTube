#!/usr/bin/env python3
"""RG News2 outbound moderation queue: max 3 unreviewed cards, no polling.
Installs guarded runner. Run 'tick' once to send at most one card.
No cron, channel sends, getUpdates, or ownership gate modification.
"""
import fcntl,json,os,pathlib,subprocess,sys
BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OWNER=BASE/"NAS_EXCLUSIVE_OWNER_VERIFIED"
DELIVERY=BASE/"MODERATION_DELIVERY_ENABLED"
PUBLISH=BASE/"PUBLISH_ENABLED"
LEGACY=pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled")
def emit(**kwargs): print(json.dumps(kwargs,ensure_ascii=False))
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ("status","tick"): raise RuntimeError("USAGE_STATUS_OR_TICK")
 if os.geteuid()!=0: raise RuntimeError("SUDO_REQUIRED")
 if PUBLISH.exists() or PUBLISH.is_symlink():raise RuntimeError("CHANNEL_GATE_MUST_STAY_CLOSED")
 if LEGACY.exists() or LEGACY.is_symlink():raise RuntimeError("LEGACY_GATE_MUST_STAY_CLOSED")
 if not DELIVERY.is_file() or DELIVERY.is_symlink():raise RuntimeError("DELIVERY_GATE_CLOSED")
 if not (BASE/"rg_moderation.py").is_file():raise RuntimeError("MODERATION_MODULE_MISSING")
 sys.path.insert(0,str(BASE))
 import rg_moderation as m
 cfg=m.config()
 if cfg["moderation_chat_id"]<=0 or cfg["moderation_chat_id"] not in cfg["moderators"]:raise RuntimeError("PERSONAL_MODERATOR_REQUIRED")
 if sys.argv[1]=="tick":
  fd=os.open(str(BASE/"operator/outbound_queue.lock"),os.O_CREAT|os.O_RDWR,0o600)
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:emit(status="ALREADY_RUNNING");return
 else:fd=None
 try:
  with m.db_connect() as db:
   rows=db.execute("SELECT state,count(*) AS n FROM moderation_dispatch GROUP BY state").fetchall()
   counts={x["state"]:x["n"] for x in rows}
   active=counts.get("sent",0)+counts.get("send_uncertain",0)
  if sys.argv[1]=="status":
   emit(status="OUTBOUND_QUEUE_STATUS",dispatch=counts,inflight=active,limit=3,channel_sends=0,telegram_polls=0);return
  if active>=3:
   emit(status="PAUSED_PENDING_MODERATION",inflight=active,limit=3,channel_sends=0,telegram_polls=0);return
  out=m.send_one()
  emit(status=out.get("status"),candidate_id=out.get("id"),message_id=out.get("message_id"),inflight_before=active,limit=3,channel_sends=0,telegram_polls=0)
 finally:
  if fd is not None:
   fcntl.flock(fd,fcntl.LOCK_UN)
   os.close(fd)
if __name__=="__main__":
 try:main()
 except Exception as ex:
  emit(status="BLOCKED",reason=str(ex) if isinstance(ex,RuntimeError) else type(ex).__name__)
  sys.exit(1)
