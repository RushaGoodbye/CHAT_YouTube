#!/bin/sh
# RG TELEGRAM V12. Offline/read-only extraction of early PREPARE exit causes.
# No deployment, container, queue, scheduler, watchdog or Telegram API actions.
set -eu
[ "$(id -u)" = "0" ] || { echo "Requires sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,os,re,shutil,time
from pathlib import Path
D=Path("/volume1/docker/RG_NAS_STATE")
print("=== RG TELEGRAM V12 PREPARE FAILURE PROOF / READ ONLY ===",flush=True)
def read(name):
    p=D/name
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>1200:return ""
        return p.read_text(encoding="utf8",errors="replace").strip()
    except OSError:return ""
def age(p):
    try:return max(0,int(time.time()-p.stat().st_mtime))
    except OSError:return "UNKNOWN"
def clip(v):
    if not isinstance(v,str):return "UNKNOWN"
    # Avoid ever outputting credentials or user data.
    if re.search(r"(?i)authorization|bearer|api[_-]?key|password|secret|authorization:|x-goog-api-key|token=|credential",v):
        return "[SENSITIVE_LINE_OMITTED]"
    v=re.sub(r"\x1b\[[0-9;]*[a-zA-Z]","",v)
    v=re.sub(r"https?://[^\s'\"]+","[URL]",v)
    v=re.sub(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b","[IP]",v)
    v=re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}","[EMAIL]",v)
    v=re.sub(r"/(?:volume1|home|root|Users|tmp)/[A-Za-z0-9_./-]+","[PATH]",v)
    v=re.sub(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)\b","[TOKEN]",v)
    v=re.sub(r"\b[a-fA-F0-9]{40,}\b","[SHA]",v)
    v=re.sub(r"\b[A-Za-z0-9+/]{48,}={0,2}\b","[LONG_VALUE]",v)
    v="".join(c for c in v if c.isprintable())
    return v[:220] if v else "[EMPTY]"
for name in ["last_deploy_status","deploy_stage","scheduler_last_check_status","last_check_status","last_error","rg_telegram_control_release_status"]:
    p=D/name
    print("STATE",name,"age_sec",age(p),"value",clip(read(name)),flush=True)
try:
    u=shutil.disk_usage("/volume1/docker")
    print("STORAGE_FREE_GB",round(u.free/1e9,2),"STORAGE_USED_PERCENT",round(u.used/u.total*100,1))
except OSError:print("STORAGE_UNKNOWN")
p=D/"auto-deploy.log"
if not p.is_file() or p.is_symlink() or p.stat().st_size>50000000:
    print("DEPLOY_LOG_UNAVAILABLE");raise SystemExit(0)
with p.open(encoding="utf8",errors="replace") as f:
    rows=list(collections.deque(f,maxlen=220))
print("DEPLOY_LOG_AGE_SEC",age(p),"TAIL_LINES",len(rows))
starts=[i for i,l in enumerate(rows) if "Downloading " in l and re.search(r"@[a-f0-9]{40}",l)]
print("DEPLOY_DOWNLOAD_CYCLES_IN_TAIL",len(starts))
for number,start in enumerate(starts[-4:],1):
    stop=(next((i for i in starts if i>start),len(rows)))
    block=rows[start:min(stop,start+24)]
    print("=== CYCLE",number,"tail_pos",start+1,"lines_to_next_cycle",stop-start,"===")
    for i,line in enumerate(block):
        s=line.strip()
        if not s:continue
        # Only diagnostics near the failed download/prepare; skip broad post data.
        if i==0:
            print("CYCLE_START",clip(s));continue
        if i<=14 and (
          re.search(r"(?i)error|failed|missing|not found|invalid|no such|cannot|tar:|curl:|traceback|exception|archive|release|syntax|warn|fatal|npm|rg_nas_",s)
          or i<=3
        ):
            print("CYCLE_DIAG",start+i+1,clip(s))
last_errs=[(i+1,x.strip()) for i,x in enumerate(rows) if re.search(r"(?i)^(?:.*\s)?(?:ERROR:|tar:|curl:|Traceback|.*(?:cannot|failed|not found|invalid|fatal).*)",x)]
print("LAST_ERROR_LINES",len(last_errs))
for i,s in last_errs[-7:]:
    print("ERR",i,clip(s))
print("RG_TELEGRAM_V12_COMPLETE_READ_ONLY",flush=True)
PY
