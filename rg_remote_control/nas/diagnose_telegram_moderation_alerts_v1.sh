#!/bin/sh
# RG Telegram live health detail v1: single authenticated READ-ONLY GET.
# Never outputs credentials, raw service payloads, user messages or URLs.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo sh"; exit 2; }
python3 - <<'PY'
import datetime as dt
import json
import pathlib
import socket
import sys
import urllib.request
from urllib.parse import urlsplit

root=pathlib.Path("/volume1/docker")
state=root/"RG_NAS_STATE"
url_file=root/"RG_NAS_CONTROL/admin_url"
token_file=root/"RG_SECRETS/rg_admin_token"
print("=== RG TELEGRAM MODERATION + KYIV ALERT HEALTH V1 (READ ONLY) ===",flush=True)

def age(t):
    if not isinstance(t,str) or len(t)>70:return "UNKNOWN"
    try:
        stamp=dt.datetime.fromisoformat(t.replace("Z","+00:00"))
        if stamp.tzinfo is None:return "UNKNOWN"
        return max(0,int((dt.datetime.now(dt.timezone.utc)-stamp).total_seconds()//60))
    except (ValueError,OverflowError):return "INVALID"

def flag(v):
    if v is True:return "TRUE"
    if v is False:return "FALSE"
    if v is None:return "UNKNOWN"
    return "NON_BOOLEAN"

def integer(v):
    if isinstance(v,bool):return "UNKNOWN"
    if isinstance(v,int) and 0<=v<=100000000:return str(v)
    if isinstance(v,str) and v.isdecimal() and len(v)<10:return v
    return "UNKNOWN"

def read_small(p,maxlen=128):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>maxlen:return "UNKNOWN"
        s=p.read_text(encoding="utf8",errors="replace").strip()
        if not s or len(s)>maxlen:return "UNKNOWN"
        return s
    except OSError:return "UNKNOWN"

print("WATCHDOG_ISSUES",end=" ")
watchdog_file=state/"telegram-watchdog-status.json"
try:
    w=json.loads(watchdog_file.read_text())
    issues=w.get("issues",[])
    names=("moderation_unhealthy","moderation_health_stale","kyiv_alert_heartbeat_stale",
           "kyiv_alert_queue_stalled","publish_queue_failed_or_uncertain","scanner_unhealthy",
           "publication_receipt_verify_failed","production_chain_blocked")
    print(",".join(x for x in issues if isinstance(x,str) and any(x.startswith(n) for n in names)) or "NONE")
    print("WATCHDOG_LAST_CHECK_AGE_MIN",age(w.get("checkedAt")))
    print("WATCHDOG_ADMIN_FETCH",w.get("adminFetch",{}).get("status") if w.get("adminFetch",{}).get("status") in ("OK","ERROR","TRANSIENT") else "UNKNOWN")
except (ValueError,OSError,AttributeError):
    print("UNKNOWN")
if not url_file.is_file() or not token_file.is_file():
    print("ADMIN_CONFIG_MISSING; no request made");sys.exit(1)
url=read_small(url_file,400)
if url=="UNKNOWN":
    print("ADMIN_URL_UNAVAILABLE; no request made");sys.exit(1)
u=urlsplit(url)
if u.scheme not in ("https","http") or not u.hostname or (u.scheme=="http" and u.hostname not in ("localhost","127.0.0.1")):
    print("ADMIN_URL_INVALID; no request made");sys.exit(1)
token=read_small(token_file,4096)
if token=="UNKNOWN":
    print("ADMIN_TOKEN_UNAVAILABLE; no request made");sys.exit(1)
try:
    req=urllib.request.Request(url.rstrip("/")+"/production-state",
        headers={"Authorization":"Bearer "+token,"Accept":"application/json","User-Agent":"RG-readonly-health-v1"},
        method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(req,timeout=16) as response:
        if response.status!=200:
            print("ADMIN_HTTP_STATUS",response.status);sys.exit(1)
        blob=response.read(8*1024*1024+1)
    if len(blob)>8*1024*1024:
        print("ADMIN_RESPONSE_TOO_LARGE");sys.exit(1)
    d=json.loads(blob)
except Exception as exc:
    print("ADMIN_READ_FAILED",type(exc).__name__)
    sys.exit(1)
if not isinstance(d,dict):
    print("ADMIN_PAYLOAD_INVALID");sys.exit(1)
print("ADMIN_PRODUCTION_STATE_FETCH OK")
production_status=d.get("status") or {}
if not isinstance(production_status,dict):
    print("STATUS_MISSING");sys.exit(1)
mod=production_status.get("telegram-video-moderation-health-v2") or {}
alert=production_status.get("air-alert-heartbeat-v1") or {}
scanner=production_status.get("telegram-video-scanner-health-v3") or {}
syshealth=production_status.get("telegram-system-health-v1") or {}
queue=d.get("queues") or {}
alerthealth=(d.get("status") or {}).get("air-alert-queue-health-v1") or {}
if not isinstance(alerthealth,dict):alerthealth={}
for field in ["moderation","alert","scanner","systemhealth"]:
    if not isinstance({"moderation":mod,"alert":alert,"scanner":scanner,"systemhealth":syshealth}[field],dict):
        print("SCHEMA_ERROR",field);sys.exit(1)
print("MODERATION_OK",flag(mod.get("ok")))
print("MODERATION_DEGRADED",flag(mod.get("degraded")))
print("MODERATION_OFFSET_BLOCKED",flag(mod.get("offsetBlocked")))
print("MODERATION_UPDATES_FAILED",integer(mod.get("updatesFailed")))
print("MODERATION_LAST_CHECK_AGE_MIN",age(mod.get("liveCheckedAt") or mod.get("checkedAt") or mod.get("updatedAt")))
print("MODERATION_KEYS_PRESENT",",".join(sorted(k for k in ("ok","degraded","offsetBlocked","updatesFailed","liveCheckedAt","checkedAt","updatedAt","publicationVerify") if k in mod)))
print("KYIV_ALERT_OK",flag(alert.get("ok")))
print("KYIV_ALERT_LAST_SUCCESSFUL_POLL_AGE_MIN",age(alert.get("lastSuccessfulPollAt")))
print("KYIV_ALERT_PROVIDER_CIRCUIT_OPEN",flag((alert.get("providerCircuit") or {}).get("ubillingOpen") if isinstance(alert.get("providerCircuit"),dict) else None))
print("KYIV_ALERT_HEARTBEAT_KEYS_PRESENT",",".join(sorted(k for k in ("ok","lastSuccessfulPollAt","providerCircuit","lastPollAt","checkedAt") if k in alert)))
print("SCANNER_OK",flag(scanner.get("ok")))
print("SCANNER_LAST_CHECK_AGE_MIN",age(scanner.get("checkedAt")))
print("SYSTEM_HEALTH_OK",flag(syshealth.get("ok")))
readiness=d.get("productionReadiness")
if isinstance(readiness,dict):
    print("PRODUCTION_READINESS_OK",flag(readiness.get("ok")))
    blocked=readiness.get("blockingStage")
    print("PRODUCTION_BLOCKING_STAGE",blocked if isinstance(blocked,str) and blocked in ("scanner","moderation","publication","alerts","content","video","VIDEO","ALERTS","CONTENT") else "NONE_OR_OTHER")
print("CONTROL_APP_STATE",read_small(state/"rg_telegram_control_app_status",30))
print("SCHEDULER_STATE",read_small(state/"scheduler_last_check_status",30))
print("RG_TELEGRAM_LIVE_HEALTH_DIAG: READONLY_DONE")
PY
