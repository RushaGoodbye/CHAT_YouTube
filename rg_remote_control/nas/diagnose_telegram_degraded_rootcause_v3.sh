#!/bin/sh
# RG Telegram: diagnose moderation degradation, production-state 503 and deploy errors.
# Read-only: no writes, queue changes, restarts, or publication calls.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo "Requires sudo sh"; exit 2; fi
python3 - <<'PY'
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path("/volume1/docker")
STATE=ROOT/"RG_NAS_STATE"
ADMIN=ROOT/"RG_NAS_CONTROL/admin_url"
TOKEN=ROOT/"RG_SECRETS/rg_admin_token"
def read(p, limit=4096):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>limit: return None
        return p.read_text(encoding="utf-8",errors="replace").strip()
    except OSError: return None
def asobj(v): return v if isinstance(v,dict) else {}
def yn(v): return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def num(v): return str(v) if type(v)==int and 0<=v<=100000000 else "UNKNOWN"
def label(v, allowed=None):
    if not isinstance(v,str) or len(v)>100 or not re.fullmatch(r"[A-Za-z0-9_.: -]{1,100}",v):
        return "UNKNOWN"
    return v if allowed is None or v in allowed else "OTHER"
def key(v): return "PRESENT" if v not in (None,"",False) else "ABSENT"
print("=== RG TELEGRAM DEGRADED ROOT CAUSE V3 READ-ONLY ===",flush=True)
for n in ("scheduler_last_check_status","scheduler_dispatch_error","last_deploy_status","deploy_stage","telegram_control_plane_status","telegram_watchdog_status"):
    p=STATE/n
    v=read(p,180)
    print("NAS",n,"value",label(v) if v is not None else "MISSING","age_sec",max(0,int(time.time()-p.stat().st_mtime)) if p.is_file() else "NA",flush=True)

url=read(ADMIN,1024)
token=read(TOKEN,4096)
if not url or not token:
    print("ADMIN_CREDENTIAL_CONFIG_MISSING");raise SystemExit(1)
u=urlsplit(url)
if u.scheme not in ("https","http") or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme=="http" and u.hostname not in ("localhost","127.0.0.1")):
    print("ADMIN_URL_NOT_ALLOWED");raise SystemExit(1)
if not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",token):
    print("ADMIN_TOKEN_FORMAT_UNEXPECTED");raise SystemExit(1)
curl=shutil.which("curl")
if not curl: print("CURL_UNAVAILABLE");raise SystemExit(1)
# Secret header passed over stdin, never on the shell command line or stdout.
cfg='header = "Authorization: Bearer '+token+'"\nconnect-timeout = 6\nmax-time = 16\n'
def get(endpoint):
    try:
        p=subprocess.run([curl,"--silent","--show-error","--config","-",
           "--max-filesize","12000000","--write-out","\nRG_HTTP_CODE_=%{http_code}",
           url.rstrip("/")+endpoint],input=cfg.encode(),capture_output=True,timeout=20,check=False)
    except (OSError,subprocess.TimeoutExpired):
        return "TIMEOUT_OR_START_ERROR",{}
    mark=b"\nRG_HTTP_CODE_="
    if mark not in p.stdout:return "CURL_FAILED",{}
    body,code=p.stdout.rsplit(mark,1)
    code=code.strip().decode("ascii","replace")
    if not re.fullmatch(r"[0-9]{3}",code):code="UNKNOWN"
    try:
        return code,asobj(json.loads(body))
    except (ValueError,UnicodeError):
        return code,{}
print("=== LIVE HTTP ===",flush=True)
status_code,status=get("/status")
print("HTTP /status",status_code,flush=True)
s=asobj(status.get("state"))
mod=asobj(s.get("telegram-video-moderation-health-v2"))
print("MODERATION_OK",yn(mod.get("ok")))
print("MODERATION_DEGRADED",yn(mod.get("degraded")))
print("MODERATION_DEGRADED_REASON",label(mod.get("degradedReason"),{
  "moderation_card_cleanup","legacy_placeholder_cleanup","broken_moderation_card_recovery"
}))
print("MODERATION_UPDATES_FAILED",num(mod.get("updatesFailed")))
print("MODERATION_OFFSET_BLOCKED",yn(mod.get("offsetBlocked")))
print("MODERATION_POLL_LEASE_DEGRADED",yn(mod.get("pollLeaseDegraded")))
for n in ("cardCleanup","placeholderCleanup","brokenCardRecovery","publicationQueue","publicationVerify"):
    v=asobj(mod.get(n))
    print("SUBSYSTEM",n,
          "present",yn(n in mod),
          "ok",yn(v.get("ok")),
          "processed",num(v.get("processed")),
          "removed",num(v.get("removed")),
          "retry",num(v.get("retry")),
          "error",key(v.get("error")),
          flush=True)
    # Only safe enums and numbers; errors may contain secrets or message content, never output.
    if n=="cardCleanup":
        r=asobj(v.get("reconciliation"))
        print("CARD_RECONCILIATION","present",yn("reconciliation" in v),
              "ok",yn(r.get("ok")),"error",key(r.get("error")),flush=True)

prod_code,prod=get("/production-state")
print("HTTP /production-state",prod_code,"body_json",yn(bool(prod)),flush=True)
if prod:
    readiness=asobj(prod.get("productionReadiness"))
    print("PRODUCTION_OK",yn(prod.get("ok")))
    print("PRODUCTION_READINESS_OK",yn(readiness.get("ok")))
    print("PRODUCTION_BLOCKING_STAGE",label(readiness.get("blockingStage")))
    print("PRODUCTION_LIVE_SMOKE_OK",yn(asobj(prod.get("liveSmoke")).get("ok")))
    print("PRODUCTION_DEPLOY_STATUS",label(asobj(prod.get("deploy")).get("status")))
else:
    print("PRODUCTION_RESPONSE_NOT_JSON_OR_EMPTY",flush=True)

nas_code,nas=get("/nas-health-public")
print("HTTP /nas-health-public",nas_code,flush=True)
if nas:
    print("NAS_HEALTH_STATUS",label(nas.get("status")))
    print("NAS_HEALTH_SYNCED",yn(nas.get("synced")))
    print("NAS_HEALTH_WORKERS_AT_HEAD",yn(nas.get("workersAtHead")))
    print("NAS_HEALTH_ERROR_PRESENT",yn(nas.get("errorPresent")))
    cb=asobj(nas.get("commandBus"))
    print("NAS_COMMAND_BUS_SYNTAX_OK",yn(cb.get("syntaxOk")))
    print("NAS_COMMAND_BUS_PHASE",label(cb.get("phase")))
    print("NAS_COMMAND_BUS_RC",num(cb.get("rc")))

# Only coarse error categories from auto-deploy logs; no raw logs, tokens or chat messages.
print("=== NAS AUTO-DEPLOY LOG DIAGNOSIS ===",flush=True)
p=STATE/"auto-deploy.log"
if p.is_file() and p.stat().st_size<=30000000:
    from collections import Counter
    with p.open(encoding="utf8",errors="replace") as f:
        from collections import deque
        lines=list(deque(f,maxlen=220))
    patterns={
       "docker_error":r"(?i)(docker.*(error|failed)|error.*docker)",
       "cloudflare_api_error":r"(?i)(cloudflare.*(error|failed)|wrangler.*(error|failed))",
       "github_error":r"(?i)(github.*(error|failed)|repository not found)",
       "http_503":r"(?i)(503|service unavailable)",
       "http_401_403":r"(?i)(401|403|unauthorized|forbidden)",
       "permission_error":r"(?i)(permission denied|operation not permitted)",
       "file_missing":r"(?i)(no such file|file not found|missing file)",
       "build_error":r"(?i)(build failed|build error|syntax error)",
       "network_error":r"(?i)(could not resolve|timed out|connection refused)",
       "deploy_failure":r"(?i)(deploy.*(failed|error)|failed.*deploy)",
    }
    counts={k:sum(bool(re.search(rx,line)) for line in lines) for k,rx in patterns.items()}
    print("DEPLOY_LOG_ANALYZED_LINES",len(lines))
    for k,v in counts.items():print("LOG_CATEGORY",k,v)
else:
    print("DEPLOY_LOG_UNAVAILABLE_OR_TOO_LARGE")
print("RG_TELEGRAM_DEGRADED_ROOTCAUSE_V3: DONE_READ_ONLY")
PY
