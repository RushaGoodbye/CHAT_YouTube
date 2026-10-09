#!/bin/sh
# R9: read-only log freshness, sanitized counts and process evidence.
set -eu
python3 - <<'PY'
import json, pathlib, re, time, datetime
root=pathlib.Path("/volume1/docker")
state=root/"RG_NAS_STATE"
files={
 "scheduler":state/"auto-deploy.log",
 "watchdog":state/"telegram-watchdog.log",
 "control_plane":state/"telegram-control-plane.log",
 "control_agent":state/"rg-telegram-control-agent.log",
 "command_bus":state/"nas-command-bus.log",
}
markers={
 "timeout":r"timeout|timed out",
 "rate_limited":r"rate.?limit|[\\s:]429(?:\\b|$)|cooldown",
 "authorization":r"(?<![0-9])(?:401|403)(?![0-9])|unauthorized|forbidden",
 "connection":r"connect(?:ion)? (?:refused|reset)|dns|network unreachable",
 "traceback":r"traceback|uncaught exception",
 "error":r"(?<![A-Za-z])error(?![A-Za-z])|(?<![A-Za-z])failed(?![A-Za-z])",
}
now=time.time()
print("RG_R9_LOG_CLASSIFICATION_READ_ONLY")
for name,path in files.items():
 result={"component":name,"present":False,"age_sec":None,"classes":{}}
 try:
  if path.is_symlink() or not path.is_file():
   print(json.dumps(result));continue
  st=path.stat()
  result["present"]=True
  result["age_sec"]=max(0,int(now-st.st_mtime)) if st.st_mtime<=now+60 else None
  with path.open("rb") as fp:
   fp.seek(max(0,st.st_size-32768))
   data=fp.read(32768).decode("utf-8","replace")
  for key,pat in markers.items():
   result["classes"][key]=len(re.findall(pat,data,re.I))
 except OSError:
  result["read_error"]=True
 print(json.dumps(result,sort_keys=True))
print("SCOPE READ_ONLY_SANITIZED_COUNTS_NO_LOG_CONTENT")
PY
