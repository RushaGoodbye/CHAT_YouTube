#!/usr/bin/env python3
"""RG Telegram NAS batch read-only health report. Python 3.8 compatible.
No network, deploy, Telegram API, Cloudflare API, writes or secret disclosure.
"""
import datetime,json,os,pathlib,sqlite3,subprocess,sys,time
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_NAS_STATE"
TG=ROOT/"RG_TELEGRAM_STATE"
def file_check(name,path,maximum=None):
 p=pathlib.Path(path)
 if not p.is_file():return {"name":name,"status":"ERROR","reason":"missing"}
 age=max(0,int(time.time()-p.stat().st_mtime))
 return {"name":name,"status":"WARNING" if maximum is not None and age>maximum else "PASS","age_sec":age}
def val(name,path,problem=None):
 p=pathlib.Path(path)
 if not p.is_file():return {"name":name,"status":"WARNING","reason":"missing"}
 value=p.read_text(errors="replace").strip()[:100]
 return {"name":name,"status":"ERROR" if value in (problem or []) else "PASS","value":value}
def probe_db():
 p=TG/"migration_shadow.sqlite3"
 if not p.is_file():return {"name":"sqlite","status":"ERROR","reason":"missing"}
 try:
  db=sqlite3.connect("file:"+str(p)+"?mode=ro",uri=True,timeout=3)
  integrity=db.execute("PRAGMA quick_check").fetchone()[0]
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  counts={}
  for table in ("events","shadow_event_receipts","shadow_queue","moderation_projection","shadow_publish_intents"):
   if table in tables:counts[table]=db.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
  if "events" in tables:
   counts["real_moderation_decisions"]=db.execute("SELECT count(*) FROM events WHERE kind='moderation_decision'").fetchone()[0]
  db.close()
  return {"name":"sqlite","status":"PASS" if integrity=="ok" else "ERROR","integrity":integrity,"counts":counts}
 except Exception as e:return {"name":"sqlite","status":"ERROR","reason":type(e).__name__}
def logtail(name,path):
 p=pathlib.Path(path)
 if not p.is_file():return {"name":name,"status":"WARNING","reason":"no_log_yet"}
 age=int(time.time()-p.stat().st_mtime)
 try:
  with p.open("rb") as f:
   f.seek(max(0,p.stat().st_size-8192)); raw=f.read()
  rows=raw.decode("utf-8","replace").splitlines()
  matches=[row for row in rows if any(word in row for word in ("SHADOW_POLL_OK","KV_IMPORT_OK","KV_COOLDOWN","SHADOW_PROJECTION_OK","BLOCKED"))]
  # Only parse JSON; do not echo arbitrary log contents.
  statuses=[]
  for row in matches[-10:]:
   try:
    doc=json.loads(row);statuses.append(str(doc.get("status","unknown"))[:50])
   except Exception:pass
  return {"name":name,"status":"PASS" if age<3600 else "WARNING","age_sec":age,"recent_statuses":statuses}
 except Exception as e:return {"name":name,"status":"WARNING","reason":type(e).__name__}
def run():
 checks=[
  file_check("scheduler_heartbeat",STATE/"scheduler_last_check_at",600),
  file_check("control_plane_heartbeat",STATE/"telegram_control_plane_last_sync_at",600),
  val("deploy_status",STATE/"last_deploy_status",["ERROR","FAILED"]),
  val("watchdog_status",STATE/"telegram_watchdog_status",["ERROR","FAILED"]),
  file_check("synology_scheduler_script",ROOT/"RG_NAS_SCHEDULER_TICK.sh"),
  file_check("kyiv_live_adapter",TG/"rg_telegram_kyiv_ubilling_live_shadow_v1.py"),
  logtail("kyiv_shadow",TG/"kyiv_shadow.log"),
  file_check("moderation_projection_module",TG/"rg_telegram_moderation_projection_v1.py"),
  logtail("moderation_shadow",TG/"moderation_shadow.log"),
  file_check("kv_bridge_module",TG/"rg_telegram_cf_kv_decision_bridge_v1.py"),
  logtail("kv_bridge_log",TG/"cf_kv_import.log"),
  probe_db(),
  file_check("cloudflare_kv_token",ROOT/"RG_SECRETS/rg_cf_kv_read_token"),
 ]
 cooldown=TG/"cf_kv_read_cooldown.json"
 if cooldown.is_file():
  try:
   remaining=max(0,int(json.loads(cooldown.read_text())["until"])-int(time.time()))
   checks.append({"name":"cloudflare_kv_cooldown","status":"WARNING" if remaining else "PASS","remaining_sec":remaining})
  except Exception:checks.append({"name":"cloudflare_kv_cooldown","status":"WARNING","reason":"invalid_state"})
 try:
  sched=(ROOT/"RG_NAS_SCHEDULER_TICK.sh").read_text(errors="replace")
  checks.append({"name":"scheduler_hooks","status":"PASS" if "RG_KV_READ_SHADOW_V1" in sched and "RG_KYIV_SHADOW_POLL_BEGIN" in sched else "WARNING","kv_import":("RG_KV_READ_SHADOW_V1" in sched),"kyiv_poll":("RG_KYIV_SHADOW_POLL_BEGIN" in sched or "RG_NAS_SHADOW_RUNTIME_V1_BEGIN" in sched)})
 except Exception:pass
 summary={x:sum(1 for c in checks if c["status"]==x) for x in ("PASS","WARNING","ERROR")}
 overall="ERROR" if summary["ERROR"] else "WARNING" if summary["WARNING"] else "PASS"
 print(json.dumps({"schema":"RG_TELEGRAM_NAS_FULL_CHECK_V1","overall":overall,"summary":summary,"checks":checks,"network_calls":0,"publish_calls":0,"modifications":0},ensure_ascii=False,indent=2))
if __name__=="__main__":run()
