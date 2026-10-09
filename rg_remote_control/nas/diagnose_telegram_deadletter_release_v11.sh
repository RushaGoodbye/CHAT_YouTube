#!/bin/sh
# RG Telegram V11: targeted read-only reason + release-transition probe.
# No deployments, scheduler/watchdog invocations, queue changes or Telegram requests.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Requires: sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
R=Path("/volume1/docker");S=R/"RG_NAS_STATE";now=time.time()
print("=== RG TELEGRAM V11 LAST BLOCKERS - READ ONLY ===",flush=True)
def txt(p,n=4096):
 try:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>n:return ""
  return p.read_text(encoding="utf-8",errors="replace").strip()
 except OSError:return ""
def age(p):
 try:return max(0,int(now-p.stat().st_mtime))
 except OSError:return "UNKNOWN"
def iso_secs(v):
 try:
  x=datetime.datetime.fromisoformat(str(v).replace("Z","+00:00"))
  return x.timestamp() if x.tzinfo else None
 except (ValueError,TypeError):return None
def human(v):
 if not isinstance(v,str):return "OTHER_OR_UNKNOWN"
 if len(v)>160 or re.search(r"(?i)https?://|token|secret|password|bearer|auth|sk-|gh[pousr]_|[A-Za-z0-9_+/=-]{25,}",v):return "REDACTED"
 if not re.fullmatch(r"[\w .,:;()!?\-=/]+",v,re.U):return "REDACTED"
 return v[:145]
def yn(v):return "TRUE" if v else "FALSE"
for name in ("last_deploy_status","deploy_stage","deploy_sync_status","last_check_status","last_error",
 "scheduler_last_check_status","telegram_startup_selftest_status","telegram_watchdog_status","rg_telegram_control_release_status"):
 p=S/name
 print("STATE",name,"value",human(txt(p,160)),"age_sec",age(p))
log=S/"auto-deploy.log"
print("=== AUTO DEPLOY LATEST PHASES ===")
if log.is_file() and not log.is_symlink() and log.stat().st_size<50000000:
 with log.open("r",encoding="utf-8",errors="replace") as f:rows=list(collections.deque(f,maxlen=220))
 print("LOG_AGE_SEC",age(log),"LOG_BYTES",log.stat().st_size)
 patterns=[
 ("download",r"Downloading \S+@[a-f0-9]{40}"),
 ("prepare_release_fail",r"Release manifest.*(?:invalid|missing)|Frozen release|archive extraction failed|tar:|No space left"),
 ("error",r"(?i)\bERROR:|error code|failed|cannot|no such file|permission denied|traceback"),
 ("start_video",r"Starting video deploy container"),
 ("start_alerts",r"Starting alerts deploy container"),
 ("start_content",r"Starting content deploy container"),
 ("smoke",r"(?i)live.smoke|production smoke"),
 ("rollback",r"ROLLBACK (?:starting|completed)"),
 ("complete",r"RG_NAS_(?:DEPLOY|CONTROL_PLANE_FAST_DEPLOY)_OK|RG_NAS_DEPLOY_UP_TO_DATE"),
 ]
 recent=rows[-85:]
 events=[]
 for index,line in enumerate(recent,1):
  kinds=[key for key,rx in patterns if re.search(rx,line)]
  if kinds:events.append((index,kinds,line))
 for i,tags,line in events[-22:]:
  payload=""
  if "error" in tags or "prepare_release_fail" in tags:
   # Deliberately don't print log lines or arbitrary strings; classify.
   categories=[]
   for name,rx in [
     ("tar",r"(?i)tar:"),("disk",r"(?i)no space|disk full"),("missing",r"(?i)no such file|missing"),
     ("frozen",r"(?i)frozen release"),("syntax",r"(?i)syntax|bad interpreter"),
     ("release",r"(?i)release.*failed|release.*invalid"),("http",r"\b(?:401|403|404|429|500|502|503)\b"),
     ("permission",r"(?i)permission denied"),("timeout",r"(?i)timed out|timeout"),
     ("worker",r"(?i)worker.*failed|deploy.*failed"),("selftest",r"(?i)self.test"),
     ("general",r"(?i)ERROR:")]:
      if re.search(rx,line):categories.append(name)
   payload=",".join(categories) if categories else "uncategorized"
  print("LOG_EVENT","last85_line",i,"phase",",".join(tags),"cause_tags",payload)
else:print("LOG_UNAVAILABLE")
root=R/"RG_RELEASES/telegram-control"
active=root/"current-release-manifest.json"
staged=list(root.glob(".current-release-manifest.json.*")) if root.is_dir() else []
print("RELEASE_ACTIVE",yn(active.is_file()),"STAGED_MANIFESTS",len(staged))
for p in staged[:5]:
 tail=p.name.rsplit(".",1)[-1]
 print("STAGED_SHA_MATCHES_HEAD",yn(tail==txt(S/"last_check_sha",100)),"stage_file_age_sec",age(p))
u=txt(R/"RG_NAS_CONTROL/admin_url",1024); secret=txt(R/"RG_SECRETS/rg_admin_token",4096)
parsed=urlsplit(u)
if not u or not secret or parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=="http" and parsed.hostname not in ("127.0.0.1","localhost")) or not re.fullmatch("[A-Za-z0-9_.~+/=-]{8,4096}",secret):
 print("ADMIN_CONFIG_UNAVAILABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:print("CURL_MISSING");raise SystemExit(1)
config='header = "Authorization: Bearer '+secret+'"\nconnect-timeout = 8\nmax-time = 20\n'
try:
 resp=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","9000000","--write-out","\nCODE:%{http_code}",u.rstrip("/")+"/queues"],
 input=config.encode(),capture_output=True,timeout=26)
 marker=b"\nCODE:"
 raw,code=resp.stdout.rsplit(marker,1) if marker in resp.stdout else (b"{}" ,b"UNKNOWN")
 doc=json.loads(raw)
 if not isinstance(doc,dict):doc={}
 print("QUEUES_HTTP",code.decode("ascii","replace").strip(),"curl_exit",resp.returncode)
except (OSError,subprocess.TimeoutExpired,ValueError) as e:
 print("QUEUES_ERROR",type(e).__name__);doc={}
state=doc.get("state") if isinstance(doc.get("state"),dict) else doc
item=state.get("telegram-video-dead-letter-v1")
items=item.get("items") if isinstance(item,dict) else item if isinstance(item,list) else []
if not isinstance(items,list):items=[]
print("DEAD_LETTER_RECORDS",len(items))
for n,row in enumerate(items[:8],1):
 if not isinstance(row,dict):continue
 reason=row.get("reason")
 category=row.get("category")
 dt=iso_secs(row.get("at"))
 src=str(row.get("sourceUrl") or "")
 pattern=re.fullmatch(r"https?://t[.]me/([A-Za-z0-9_]{4,})/(\d+)",src.strip())
 print("RECORD",n,
       "category",human(category),
       "reason",human(reason),
       "age_minutes",(round((now-dt)/60) if dt else "UNKNOWN"),
       "attempts",(row.get("attempts") if type(row.get("attempts"))==int and 0<=row.get("attempts")<=100 else "UNKNOWN"),
       "recovery_attempts",(row.get("recoveryAttempts") if type(row.get("recoveryAttempts"))==int and 0<=row.get("recoveryAttempts")<=100 else "UNKNOWN"),
       "source_link_usable",yn(pattern is not None),
       "recovery_last_error",human(row.get("recoveryLastError")))
print("RG_TELEGRAM_V11_COMPLETE_READ_ONLY")
PY
