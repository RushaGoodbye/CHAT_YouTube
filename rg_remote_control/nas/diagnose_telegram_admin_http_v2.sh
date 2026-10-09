#!/bin/sh
# Telegram admin API response codes and safe health evidence.
# READ ONLY: no service restarts, no files written, no Telegram posts, no queue changes.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "Requires sudo sh"; exit 2; fi
python3 - <<'PY'
import concurrent.futures as cf
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

root=Path("/volume1/docker")
state=root/"RG_NAS_STATE"
latest=root/"RG_TELEGRAM/latest"
def read(p,limit=8192):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > limit: return ""
        return p.read_text(encoding="utf-8",errors="replace").strip()
    except OSError: return ""
def mins(v):
    if not isinstance(v,str):return "UNKNOWN"
    try:
        x=dt.datetime.fromisoformat(v.replace("Z","+00:00"))
        if x.tzinfo is None:return "UNKNOWN"
        return max(0,int((dt.datetime.now(dt.timezone.utc)-x).total_seconds()/60))
    except Exception:return "UNKNOWN"
def bools(v): return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def metric(v):
    if type(v)==int and 0<=v<100000000:return v
    return "UNKNOWN"
def evidence(label,mod,alert,scanner,publish):
    print("=== "+label+" ===",flush=True)
    print("MODERATION_OK",bools(mod.get("ok")))
    print("MODERATION_DEGRADED",bools(mod.get("degraded")))
    print("MODERATION_OFFSET_BLOCKED",bools(mod.get("offsetBlocked")))
    print("MODERATION_UPDATES_FAILED",metric(mod.get("updatesFailed")))
    print("MODERATION_LAST_CHECK_AGE_MIN",mins(mod.get("liveCheckedAt") or mod.get("checkedAt") or mod.get("updatedAt")))
    print("ALERT_OK",bools(alert.get("ok")))
    print("ALERT_LAST_SUCCESSFUL_POLL_AGE_MIN",mins(alert.get("lastSuccessfulPollAt")))
    print("ALERT_PROVIDER_UBILLING_OPEN",bools((alert.get("providerCircuit") or {}).get("ubillingOpen") if isinstance(alert.get("providerCircuit"),dict) else None))
    print("SCANNER_OK",bools(scanner.get("ok")))
    print("SCANNER_LAST_CHECK_AGE_MIN",mins(scanner.get("checkedAt")))
    print("PUBLISH_FAILED",metric(publish.get("failed")))
    print("PUBLISH_UNCERTAIN",metric(publish.get("uncertain")))
def obj(x): return x if isinstance(x,dict) else {}
def health(data):
    if not isinstance(data,dict):return {},{},{},{}
    # /production-state returns "status", /status and /alerts return "state".
    st=obj(data.get("status")) or obj(data.get("state"))
    qs=obj(data.get("queues") or data.get("state"))
    return (obj(st.get("telegram-video-moderation-health-v2")),
            obj(st.get("air-alert-heartbeat-v1")),
            obj(st.get("telegram-video-scanner-health-v3")),
            obj(qs.get("telegram-moderation-publish-health-v2")))
def loadj(p):
    try:
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 16000000:return {}
        return obj(json.loads(p.read_text(encoding="utf-8",errors="replace")))
    except Exception:return {}
print("=== RG TELEGRAM ADMIN HTTP STATUS DIAGNOSTIC V2 - READ ONLY ===",flush=True)
print("NAS_LOCAL_TIME",dt.datetime.now().astimezone().isoformat(timespec="seconds"))
print("WATCHDOG_FETCH_STATUS",read(state/"telegram_watchdog_admin_fetch_status",25) or "UNKNOWN")
print("WATCHDOG_FETCH_FAILURE_COUNT",read(state/"telegram_watchdog_admin_fetch_failure_count",10) or "UNKNOWN")
print("SCHEDULER_STATUS",read(state/"scheduler_last_check_status",25) or "UNKNOWN")
print("CONTROL_PLANE_STATUS",read(state/"telegram_control_plane_status",25) or "UNKNOWN")
for fn in ["production.json","status.json","alerts.json","queues.json"]:
    p=latest/fn
    if p.is_file() and not p.is_symlink():
        print("LOCAL_SNAPSHOT",fn,"age_min",round(max(0,time.time()-p.stat().st_mtime)/60,1))
production=loadj(latest/"production.json")
st=loadj(latest/"status.json")
al=loadj(latest/"alerts.json")
qu=loadj(latest/"queues.json")
pm,pa,ps,pp=health(production)
sm,sa,ss,sp=health(st)
am,aa,as_,ap=health(al)
qm,qa,qs,qp=health(qu)
if any((pm,pa,ps,pp,sm,sa,ss,sp,aa,qp)):
    evidence("CACHED HEALTH (NOT PROOF OF LIVE DELIVERY)",pm or sm,pa or aa,ps or ss,pp or qp)
curl=shutil.which("curl")
if not curl:
    print("CURL_NOT_FOUND");sys.exit(1)
u=read(root/"RG_NAS_CONTROL/admin_url",2048)
token=read(root/"RG_SECRETS/rg_admin_token",4096)
if not u or not token:
    print("ADMIN_CONFIG_MISSING");sys.exit(1)
parsed=urlsplit(u)
if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in ("https","http") or (parsed.scheme=="http" and parsed.hostname not in ("localhost","127.0.0.1")):
    print("ADMIN_URL_NOT_ALLOWED");sys.exit(1)
if not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",token):
    print("TOKEN_FORMAT_NOT_ALLOWED");sys.exit(1)
# Credentials sent to curl via standard input, not in process arguments or logs.
curl_cfg='header = "Authorization: Bearer '+token+'"\nconnect-timeout = 6\nmax-time = 14\n'
marker=b"\nRG_HTTP_CODE_="
def get(path):
    url=u.rstrip("/")+path
    try:
        p=subprocess.run([curl,"--silent","--show-error","--config","-",
             "--max-filesize","16000000","--header","Accept: application/json",
             "--write-out","\nRG_HTTP_CODE_=%{http_code}",url],
            input=curl_cfg.encode(),capture_output=True,timeout=18)
        if marker not in p.stdout: return path,None,None,p.returncode
        data,code=p.stdout.rsplit(marker,1)
        code=code.strip().decode("ascii","replace")
        parsed_data={}
        if code=="200" and len(data)<16000000:
            try:parsed_data=obj(json.loads(data))
            except ValueError: pass
        return path,code,parsed_data,p.returncode
    except Exception:return path,None,None,-1
print("=== LIVE ADMIN API HTTP CODES ===",flush=True)
paths=["/production-state","/status","/alerts","/queues"]
with cf.ThreadPoolExecutor(max_workers=4) as pool:
    got=list(pool.map(get,paths))
for name,code,data,exitcode in got:
    print("API",name,"HTTP",code or "UNKNOWN","CURL_EXIT",exitcode,flush=True)
    if code=="200" and data:
        m,a,s,p=health(data)
        if name=="/production-state":
            evidence("LIVE PRODUCTION STATE",m,a,s,p)
        elif name=="/status":
            evidence("LIVE MODERATION AND SCANNER STATUS",m,{},s,{})
        elif name=="/alerts":
            evidence("LIVE KYIV ALERT STATUS",{},a,{},{})
        elif name=="/queues":
            evidence("LIVE PUBLISH QUEUE HEALTH",{}, {},{},p)
print("RG_TELEGRAM_HTTP_DIAG: DONE_READ_ONLY",flush=True)
PY
