#!/usr/bin/env python3
"""News2 single-card controlled test kit. Read-only preflight and fail-closed rollback.
No Telegram API calls, no polling, no channel publishing.
This kit never fabricates exclusivity proof or opens owner/delivery gates.
"""
import datetime,json,os,pathlib,sqlite3,sys,urllib.parse,shutil
N=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
STATE=N/"operator"
GATES=["NAS_EXCLUSIVE_OWNER_VERIFIED","MODERATION_DELIVERY_ENABLED","PUBLISH_ENABLED"]
LEGACY=pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled")
def state():
 d={"schema":"RG_NEWS2_SINGLE_CARD_KIT_V1","time":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "queue":{},"candidate":None,"gates":{x:(N/x).is_file() for x in GATES},
    "legacy_gate":LEGACY.exists(),"single_owner_proven":False,
    "telegram_calls":0,"messages_sent":0,"database_writes":0}
 dbp=N/"news.sqlite3"
 if dbp.is_file():
  with sqlite3.connect("file:"+urllib.parse.quote(str(dbp),safe="/")+"?mode=ro",uri=True,timeout=5) as db:
   db.row_factory=sqlite3.Row
   d["queue"]={str(x[0]):x[1] for x in db.execute("SELECT status,count(*) FROM candidates GROUP BY status")}
   row=db.execute("""SELECT id,status,photo_url,caption FROM candidates
       WHERE status='awaiting_photo_review' AND photo_url IS NOT NULL AND photo_url!=''
       ORDER BY created_at DESC LIMIT 1""").fetchone()
   if row:
    u=urllib.parse.urlsplit(str(row["photo_url"]))
    d["candidate"]={"id":row["id"],"status":row["status"],
      "caption_preview":str(row["caption"] or "")[:130],
      "photo_host":u.hostname,"https":u.scheme=="https"}
 return d
def preflight():
 d=state()
 d["readiness"]="BLOCKED_NOT_ACTIVATED"
 d["blockers"]=[]
 if not (N/"rg_moderation.py").is_file():d["blockers"].append("MODERATION_MODULE_MISSING")
 if not (STATE/"moderation_tick.sh").is_file():d["blockers"].append("RUNNER_NOT_STAGED")
 if not d["candidate"]:d["blockers"].append("NO_IMAGE_CANDIDATE")
 if d["legacy_gate"]:d["blockers"].append("OLD_BOT_GATE_ACTIVE")
 if not d["gates"]["NAS_EXCLUSIVE_OWNER_VERIFIED"]:d["blockers"].append("EXCLUSIVE_OWNER_NOT_ATTESTED")
 if not d["gates"]["MODERATION_DELIVERY_ENABLED"]:d["blockers"].append("MODERATION_SEND_DISABLED")
 d["channel_publishing_enabled"]=d["gates"]["PUBLISH_ENABLED"]
 if d["channel_publishing_enabled"]:d["blockers"].append("PUBLISH_GATE_OPEN_TEST_REFUSED")
 print(json.dumps(d,ensure_ascii=False,indent=2))
def rollback():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 # Disable only moderation delivery. Do not modify authoritative owner marker or legacy bot gate.
 target=N/"MODERATION_DELIVERY_ENABLED"
 if target.is_symlink():raise RuntimeError("DELIVERY_GATE_SYMLINK_REFUSED")
 if target.is_file():
  backup=STATE/("disabled_delivery_"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
  if backup.exists():raise RuntimeError("BACKUP_EXISTS")
  STATE.mkdir(mode=0o700,exist_ok=True)
  shutil.copy2(str(target),str(backup))
  target.unlink()
  print(json.dumps({"result":"MODERATION_DELIVERY_DISABLED","backup":str(backup),"publisher_untouched":True}))
 else:
  print(json.dumps({"result":"ALREADY_DISABLED","publisher_untouched":True}))
def main():
 if len(sys.argv)!=2 or sys.argv[1] not in ("preflight","rollback"):
  print("usage: single_card_kit.py preflight|rollback");return 2
 if sys.argv[1]=="preflight":preflight()
 else:rollback()
 return 0
if __name__=="__main__":
 try:sys.exit(main())
 except Exception as ex:
  print(json.dumps({"result":"BLOCKED","reason":type(ex).__name__}));sys.exit(1)
