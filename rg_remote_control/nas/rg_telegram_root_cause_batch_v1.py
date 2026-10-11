#!/usr/bin/env python3
"""One-shot read-only evidence collector for the Telegram production failure.
Only allowlisted status/log paths; redact secrets, URLs, identifiers.
No network/API calls, publication, DB mutations or process restarts.
"""
import os, pathlib, json, re, time, sqlite3
ROOT=pathlib.Path("/volume1/docker")
S=ROOT/"RG_NAS_STATE";T=ROOT/"RG_TELEGRAM_STATE"
patterns=[("state",S),("telegram",T),("deploy",ROOT/"RG_ALERTS_DEPLOY")]
filenames=("telegram_watchdog_status","live_smoke_status","last_deploy_status","deploy_stage","scheduler_last_check_status","scheduler_dispatch_error","telegram_watchdog_issues","nas_command_bus_error")
terms=("error","failed","stale","scanner","moderation","publish","quota","watchdog","429","defer")
def safe(s):
 s=re.sub(r"https?://\S+","[URL]",str(s))
 s=re.sub(r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[:=]\s*\S+",r"\1=[REDACTED]",s)
 s=re.sub(r"\b\d{7,}\b","[ID]",s)
 return s[:180]
out=[]
for group,folder in patterns:
 if not folder.is_dir():continue
 if group=="deploy":continue
 for name in filenames:
  p=folder/name
  if p.is_file() and p.stat().st_size<131072:
   val=safe(p.read_text("utf-8","replace").strip())
   out.append({"group":group,"name":name,"age_sec":int(time.time()-p.stat().st_mtime),"value":val})
# Limit log scan to known NAS log directories and recent log files; do not print arbitrary log lines.
logs=[]
for base in (S,T):
 if not base.is_dir():continue
 for p in sorted(base.glob("*.log"))[:120]:
  try:
   if time.time()-p.stat().st_mtime>86400:continue
   with p.open("rb") as f:
    f.seek(max(0,p.stat().st_size-32768)); txt=f.read().decode("utf-8","replace")
   lines=txt.splitlines()
   interesting=[safe(x) for x in lines if any(term in x.lower() for term in terms)]
   logs.append({"name":p.name,"age_sec":int(time.time()-p.stat().st_mtime),"matches":len(interesting),"last":interesting[-3:]})
  except (OSError,ValueError):pass
print(json.dumps({"schema":"RG_TELEGRAM_ROOT_CAUSE_BATCH_V1","statuses":out,"logs":logs,"read_only":True,"network_calls":0,"telegram_sends":0},ensure_ascii=False,indent=2))
