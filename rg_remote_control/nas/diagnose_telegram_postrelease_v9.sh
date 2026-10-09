#!/bin/sh
# RG Telegram post-release readiness diagnosis V9. Strictly read-only.
# No deployments, scheduler calls, restarts, queue mutations or publications.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo sh"; exit 2; }
python3 - <<'PY'
import datetime,json,re,shutil,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path("/volume1/docker")
S=ROOT/"RG_NAS_STATE"
print("=== RG TELEGRAM V9 POST-RELEASE READINESS (READ ONLY) ===",flush=True)
print("NOW_KYIV",datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(timespec="seconds"))
def txt(path,limit=2048):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:return ""
        return path.read_text(encoding="utf-8",errors="replace").strip()
    except OSError:return ""
def obj(v):return v if isinstance(v,dict) else {}
def yn(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def age(path):
    try:return max(0,int(time.time()-path.stat().st_mtime))
    except OSError:return "UNKNOWN"
def token(v):
    if not isinstance(v,str) or not re.fullmatch("[A-Za-z0-9_.:-]{1,90}",v):return "OTHER"
    return v
for name in ("last_deploy_status","deploy_stage","deploy_sync_status","live_smoke_status",
             "scheduler_last_check_status","scheduler_dispatch_error","last_check_status",
             "telegram_startup_selftest_status","telegram_startup_selftest_error",
             "telegram_control_plane_status","telegram_watchdog_status"):
    p=S/name
    v=txt(p,150)
    print("STATE",name,"value",token(v) if v else "MISSING","age_sec",age(p),flush=True)
for name in ("selftest_details","telegram-watchdog-status.json"):
    p=S/name
    print("REPORT",name,"age_sec",age(p),"exists",yn(p.is_file()))
details=txt(S/"selftest_details",32000)
if details:
    # These are fixed self-test labels, not arbitrary log content; never print raw lines.
    passed=details.count("✅")
    failed=details.count("❌")
    print("SELFTEST_CHECKS","passed",passed,"failed",failed)
    for line in details.splitlines():
        if "❌" not in line:continue
        name=line.split("❌",1)[-1].strip()
        if re.fullmatch("[A-Za-z0-9 ._:/()-]{1,90}",name):
            print("SELFTEST_FAILED_CHECK",name)
        else:print("SELFTEST_FAILED_CHECK","OTHER")
watch_path=S/"telegram-watchdog-status.json"
w={}
try:
    if watch_path.is_file() and not watch_path.is_symlink() and watch_path.stat().st_size<1200000:
        w=obj(json.loads(watch_path.read_text(encoding="utf-8",errors="replace")))
except (OSError,ValueError,UnicodeError):pass
print("WATCHDOG_REPORT","ok",yn(w.get("ok")),"full",yn(w.get("fullCheck")),"issue_count",len(w.get("issues") or []) if isinstance(w.get("issues"),list) else "UNKNOWN","admin_fetch",token(obj(w.get("adminFetch")).get("status")),"admin_failures",obj(w.get("adminFetch")).get("consecutiveFailures") if type(obj(w.get("adminFetch")).get("consecutiveFailures"))==int else "UNKNOWN")
for issue in (w.get("issues") if isinstance(w.get("issues"),list) else [])[:25]:
    print("WATCHDOG_ISSUE",token(issue))
for warn in (w.get("warnings") if isinstance(w.get("warnings"),list) else [])[:12]:
    print("WATCHDOG_WARNING",token(warn))
print("=== LIVE ADMIN PRODUCTION READINESS ===",flush=True)
url=txt(ROOT/"RG_NAS_CONTROL/admin_url",1024)
auth=txt(ROOT/"RG_SECRETS/rg_admin_token",4096)
u=urlsplit(url)
if not url or not auth or u.scheme not in ("https","http") or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme=="http" and u.hostname not in ("127.0.0.1","localhost")) or not re.fullmatch("[A-Za-z0-9_.~+/=-]{8,4096}",auth):
    print("ADMIN_CONFIG_NOT_USABLE");raise SystemExit(1)
curl=shutil.which("curl")
if not curl: print("CURL_NOT_FOUND");raise SystemExit(1)
cfg='header = "Authorization: Bearer '+auth+'"\nconnect-timeout = 8\nmax-time = 25\n'
def get(path):
    try:
        cp=subprocess.run([curl,"--silent","--show-error","--config","-",
          "--max-filesize","10000000","--write-out","\nHTTP_CODE:%{http_code}",url.rstrip("/")+path],
          input=cfg.encode(),capture_output=True,timeout=30,check=False)
        marker=b"\nHTTP_CODE:"
        if marker not in cp.stdout:return "UNKNOWN",{},cp.returncode
        raw,code=cp.stdout.rsplit(marker,1)
        code=code.decode("ascii","replace").strip()
        try: payload=obj(json.loads(raw))
        except (ValueError,UnicodeError):payload={}
        return code if re.fullmatch("[0-9]{3}",code) else "UNKNOWN",payload,cp.returncode
    except (OSError,subprocess.TimeoutExpired):return "UNKNOWN",{},-1
http,doc,rc=get("/production-state")
ready=obj(doc.get("productionReadiness"))
print("PRODUCTION","http",http,"curl_exit",rc,"ok",yn(doc.get("ok")),"readiness_ok",yn(ready.get("ok")),"blocking_stage",token(ready.get("blockingStage")),"stage_count",len(ready.get("stages") or []) if isinstance(ready.get("stages"),list) else "UNKNOWN",flush=True)
for stage in (ready.get("stages") if isinstance(ready.get("stages"),list) else [])[:30]:
    if not isinstance(stage,dict):continue
    if stage.get("ok") is not True:
        print("FAILED_STAGE","id",token(stage.get("id")),"detail_class",token(stage.get("detail")) if isinstance(stage.get("detail"),str) and len(stage.get("detail"))<91 and re.fullmatch("[A-Za-z0-9_.:-]+",stage.get("detail")) else "COMPLEX_OR_REDACTED")
dep=obj(doc.get("deploy"))
smoke=obj(doc.get("liveSmoke"))
print("LIVE","deploy_status",token(dep.get("status")),"smoke_ok",yn(smoke.get("ok")),"smoke_failed_count",len(smoke.get("failed") or []) if isinstance(smoke.get("failed"),list) else "UNKNOWN")
for v in (smoke.get("failed") if isinstance(smoke.get("failed"),list) else [])[:20]:
    print("LIVE_FAILED_CHECK",token(v))
status=obj(doc.get("status"))
mod=obj(status.get("telegram-video-moderation-health-v2"))
if not mod:mod=obj(obj(status.get("state")).get("telegram-video-moderation-health-v2"))
broken=obj(mod.get("brokenCardRecovery"))
print("LIVE_MODERATION","ok",yn(mod.get("ok")),"degraded",yn(mod.get("degraded")),"error_present",yn(bool(broken.get("error"))))
print("RG_TELEGRAM_V9: COMPLETE_READ_ONLY",flush=True)
PY
