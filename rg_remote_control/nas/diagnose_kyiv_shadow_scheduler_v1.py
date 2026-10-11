#!/usr/bin/env python3
"""RG NAS Kyiv shadow scheduler diagnostic: read-only; no API calls, no process starts."""
import pathlib,json,time,subprocess
R=pathlib.Path("/volume1/docker")
paths={
"scheduler":R/"RG_NAS_SCHEDULER_TICK.sh",
"adapter":R/"RG_TELEGRAM_STATE/rg_telegram_kyiv_ubilling_live_shadow_v1.py",
"log":R/"RG_TELEGRAM_STATE/kyiv_shadow.log",
"scheduler_heartbeat":R/"RG_NAS_STATE/scheduler_last_check_at",
"runtime_heartbeat":R/"RG_NAS_STATE/telegram_control_plane_last_sync_at"}
out={}
for key,p in paths.items():
 if p.is_file():
  st=p.stat()
  item={"exists":True,"age_sec":max(0,int(time.time()-st.st_mtime)),"bytes":st.st_size}
  if key=="scheduler":
   t=p.read_text("utf-8",errors="replace")
   item["hook_present"]="RG_KYIV_SHADOW_POLL_BEGIN" in t
   item["hook_before_autodeploy"]=t.find("RG_KYIV_SHADOW_POLL_BEGIN")<t.find('AUTODEPLOY="$ROOT/RG_NAS_AUTO_DEPLOY.sh"')
  if key=="log":
   rows=p.read_text("utf-8",errors="replace").splitlines()
   item["last_lines"]=[x[:240] for x in rows[-6:]]
  out[key]=item
 else:out[key]={"exists":False}
try:
 p=subprocess.run(["/bin/sh","-n",str(paths["scheduler"])],capture_output=True,text=True,timeout=8)
 out["shell_syntax_ok"]=p.returncode==0
except Exception as e:out["shell_syntax_error"]=type(e).__name__
# Synology task registry - count/safely identify command references only, do not dump task secrets.
for candidate in ("/usr/syno/etc/synoschedtask.conf","/etc/crontab"):
 p=pathlib.Path(candidate)
 if p.is_file():
  txt=p.read_text("utf-8",errors="replace")
  out["task_registry_"+p.name]={"exists":True,"mentions_scheduler":txt.count("RG_NAS_SCHEDULER_TICK"),"mentions_shadow":txt.count("RG_KYIV_SHADOW")}
print(json.dumps({"schema":"RG_KYIV_SCHED_DIAG_V1","read_only":True,"data":out},ensure_ascii=False))
