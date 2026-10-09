#!/bin/sh
# RG Telegram V6: compare authenticated read-only moderation list limits.
# Does not restart services, post, touch queues, deploy, or write any files.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Requires sudo sh"; exit 2; }
python3 - <<'PY'
import datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
R=Path("/volume1/docker");S=R/"RG_NAS_STATE"
print("=== RG TELEGRAM V6 HTTP403 CAUSE + DEPLOY CYCLE (READ ONLY) ===",flush=True)
def read(p,limit=4096):
  try:
    if not p.is_file() or p.is_symlink() or p.stat().st_size>limit:return ""
    return p.read_text(encoding="utf-8",errors="replace").strip()
  except OSError:return ""
def classify(text):
  if not isinstance(text,str) or not text:return "NONE"
  m=re.search(r"\b(?:HTTP|status)\s*(\d{3})\b",text,re.I)
  if m:return "HTTP_"+m.group(1)
  for pattern,kind in [
    (r"permission|forbidden","FORBIDDEN"),(r"not found|no such file","MISSING_RESOURCE"),
    (r"timeout|timed out","TIMEOUT"),(r"api token|unauthorized","AUTH"),
    (r"failed to fetch|connection","NETWORK"),(r"syntax error|bad interpreter","SYNTAX"),
    (r"durable|storage|kv","STORAGE"),(r"quota|rate limit|too many","RATE_LIMIT")]:
      if re.search(pattern,text,re.I):return kind
  return "OTHER"
def boolish(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def num(v):
  if type(v)==int and 0<=v<=999999:return v
  return "UNKNOWN"
def ago(path):
  try:return max(0,int(time.time()-path.stat().st_mtime))
  except OSError:return "UNKNOWN"
def safeval(v):
  allow={"OK","ERROR","RUNNING","DEPLOYING","SYNCED","DEGRADED","VIDEO","ALERTS","CONTENT","LIVE_SMOKE","PREPARE","COMPLETE","CONTROL_PLANE","IDLE"}
  return v if v in allow else "OTHER_OR_UNKNOWN"
print("TIME",datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
for name in ("last_deploy_status","deploy_stage","scheduler_last_check_status","telegram_watchdog_status","telegram_control_plane_status","deploy_sync_status"):
  p=S/name
  print("STATE",name,"value",safeval(read(p,256)),"age_sec",ago(p),flush=True)
u=read(R/"RG_NAS_CONTROL/admin_url",1024)
t=read(R/"RG_SECRETS/rg_admin_token",4096)
parsed=urlsplit(u)
if not u or not t or parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=="http" and parsed.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch("[A-Za-z0-9_.~+/=-]{8,4096}",t):
  print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl: print("CURL_MISSING");raise SystemExit(1)
cfg='header = "Authorization: Bearer '+t+'"\nconnect-timeout = 8\nmax-time = 18\n'
def get(path):
  try:
    p=subprocess.run([curl,"--silent","--show-error","--config","-",
      "--max-filesize","12000000","--write-out","\nRG_CODE:%{http_code}",u.rstrip("/")+path],
      input=cfg.encode(),capture_output=True,timeout=24)
    delim=b"\nRG_CODE:"
    if delim not in p.stdout:return "UNKNOWN",{},"NO_HTTP_MARKER",p.returncode
    raw,code=p.stdout.rsplit(delim,1)
    code=code.decode("ascii","replace").strip()
    try:
      body=json.loads(raw)
    except Exception:body={}
    return code,body if isinstance(body,dict) else {},"OK",p.returncode
  except Exception:return "UNKNOWN",{},"EXECUTION_ERROR",-1
print("=== INTERNAL COORDINATOR BY REQUEST LIMIT ===",flush=True)
for limit in (1,80,250,500):
  path="/moderation-candidates?limit="+str(limit)
  code,d,note,rc=get(path)
  print("REQUEST limit",limit,"HTTP",code,"curl_exit",rc,
        "api_ok",boolish(d.get("ok")),"count",num(d.get("count")),
        "matched",num(d.get("matched")),"scanned",num(d.get("scanned")),
        "error_class",classify(d.get("error")),flush=True)
code,d,note,rc=get("/status")
mod=(d.get("state") or {}).get("telegram-video-moderation-health-v2") if isinstance(d.get("state"),dict) else None
mod=mod if isinstance(mod,dict) else {}
broken=mod.get("brokenCardRecovery")
broken=broken if isinstance(broken,dict) else {}
print("MODERATION_HEALTH_HTTP",code,"ok",boolish(mod.get("ok")),"degraded",boolish(mod.get("degraded")),
      "brokenCardError",classify(broken.get("error")),"brokenCardRan",boolish(broken.get("ran")),flush=True)
print("=== RECENT DEPLOY OUTCOME MARKERS ONLY ===",flush=True)
log=S/"auto-deploy.log"
if log.is_file() and not log.is_symlink() and log.stat().st_size<30000000:
  from collections import deque
  with log.open(encoding="utf-8",errors="replace") as f:
    rows=list(deque(f,maxlen=500))
  keywords=[
    ("deploy_success",r"RG_NAS_DEPLOY_OK|full telegram release activated"),
    ("rollback",r"ROLLBACK completed"),
    ("video_deploy_fail",r"Video Worker deploy failed"),
    ("alerts_deploy_fail",r"Alert Worker deploy failed"),
    ("content_deploy_fail",r"Content Worker deploy failed"),
    ("live_smoke_fail",r"Live production smoke test failed"),
    ("syntax_fail",r"syntax invalid|syntax error"),
    ("missing_file",r"no such file"),
    ("deploy_other_fail",r"ERROR:"),
  ]
  for scope,size in [("last100",100),("last500",500)]:
    lines=rows[-size:]
    for key,rx in keywords:
      count=sum(bool(re.search(rx,line,re.I)) for line in lines)
      if count:print("LOG_MARKER",scope,key,count,flush=True)
  print("DEPLOY_LOG_AGE_SEC",ago(log),"DEPLOY_LOG_BYTES",log.stat().st_size)
else:print("DEPLOY_LOG_NOT_AVAILABLE")
print("RG_TELEGRAM_V6_DONE_READONLY",flush=True)
PY
