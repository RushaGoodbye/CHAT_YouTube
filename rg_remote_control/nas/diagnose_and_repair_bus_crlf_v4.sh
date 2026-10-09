#!/bin/sh
# V4: diagnose live moderation & deployment and conditionally fix CRLF in Command Bus only.
# Does not run scheduler, deploy, Telegram actions or alter queues.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "ERROR: requires sudo sh"; exit 2; }
python3 - <<'PY'
import collections, datetime, json, os, re, shutil, stat, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlsplit

R=Path("/volume1/docker"); S=R/"RG_NAS_STATE"; bus=R/"RG_NAS_COMMAND_BUS.sh"
print("=== RG TELEGRAM ROOTCAUSE + SAFE BUS CRLF REPAIR V4 ===",flush=True)
def synt(data):
    try:
        return subprocess.run(["/bin/sh","-n"],input=data,capture_output=True,timeout=12).returncode==0
    except Exception:return False
def fix_bus():
    if bus.is_symlink() or not bus.is_file():print("BUS_FILE MISSING_OR_SYMLINK");return
    a=bus.read_bytes(); crlf=a.count(b"\r\n"); fixed=a.replace(b"\r\n",b"\n")
    print("BUS_PREFLIGHT","CRLF",crlf,"before_syntax", "PASS" if synt(a) else "ERROR",
          "after_syntax","PASS" if synt(fixed) else "ERROR")
    if not crlf:
        print("BUS_REPAIR SKIPPED_NO_CRLF");return
    if b"\r" in fixed or not fixed.startswith(b"#!/bin/sh\n") or not synt(fixed):
        print("BUS_REPAIR REFUSED_UNSAFE");return
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base=S/"telegram_crlf_backups"/("bus_"+stamp)
    try:
        base.mkdir(parents=True,mode=0o700,exist_ok=False)
        backup=base/"RG_NAS_COMMAND_BUS.sh.bak"
        with backup.open("xb") as f: f.write(a);f.flush();os.fsync(f.fileno())
        backup.chmod(0o600)
        if backup.read_bytes()!=a:raise RuntimeError("BACKUP_MISMATCH")
        info=bus.stat()
        fd,tmp=tempfile.mkstemp(prefix=".rg-bus-lf.",dir=str(R))
        try:
            with os.fdopen(fd,"wb") as f: f.write(fixed);f.flush();os.fsync(f.fileno())
            os.chmod(tmp,stat.S_IMODE(info.st_mode))
            os.chown(tmp,info.st_uid,info.st_gid)
            if bus.read_bytes()!=a:raise RuntimeError("FILE_CHANGED_DURING_PREFLIGHT")
            os.replace(tmp,bus)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        if bus.read_bytes()!=fixed or not synt(bus.read_bytes()):
            # Restore from verified backup with another atomic write.
            fd,tmp=tempfile.mkstemp(prefix=".rg-bus-rollback.",dir=str(R))
            try:
                with os.fdopen(fd,"wb") as f: f.write(a);f.flush();os.fsync(f.fileno())
                os.chmod(tmp,stat.S_IMODE(info.st_mode))
                os.chown(tmp,info.st_uid,info.st_gid)
                os.replace(tmp,bus)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
            print("BUS_REPAIR ROLLED_BACK_POSTCHECK")
        else:
            print("BUS_REPAIR FIXED_LF_SYNTAX_PASS","BACKUP",str(backup))
    except Exception as e:
        print("BUS_REPAIR FAILED",type(e).__name__,str(e) if str(e) in ("BACKUP_MISMATCH","FILE_CHANGED_DURING_PREFLIGHT") else "INTERNAL_ERROR")
fix_bus()

def getfile(p,n=8192):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>n:return None
        return p.read_text(encoding="utf-8",errors="replace").strip()
    except OSError:return None
def enum(v,allowed):
    return v if isinstance(v,str) and v in allowed else "UNKNOWN"
def bo(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def number(v):return v if type(v)==int and 0<=v<=100000000 else "UNKNOWN"
def ob(v):return v if isinstance(v,dict) else {}
def classify_error(s):
    if not isinstance(s,str) or not s:return "NONE"
    for code in re.findall(r"\b(?:HTTP|status)\s*(\d{3})\b",s,re.I):
        return "INTERNAL_HTTP_"+code
    for rx,category in [
      (r"not found|no such file|unknown route","MISSING_ENDPOINT_OR_RESOURCE"),
      (r"timed? ?out|deadline","TIMEOUT"),
      (r"token|unauthorized|forbidden|authentication","AUTH_ERROR"),
      (r"quota|limit|too many requests|rate.lim","RATE_OR_QUOTA"),
      (r"fetch failed|connection|network|dns","NETWORK"),
      (r"get\s+of\s+undefined|undefined|is not a function|typeerror","CODE_TYPE_ERROR"),
      (r"storage|durable|kv|read only|transaction","STATE_STORAGE"),
      (r"out of memory|memory","RESOURCE_LIMIT"),
    ]:
        if re.search(rx,s,re.I):return category
    return "OTHER_ERROR"
for n in ("scheduler_last_check_status","scheduler_dispatch_error","telegram_control_plane_status",
          "telegram_watchdog_status","last_deploy_status","deploy_stage","live_smoke_status"):
    v=getfile(S/n,200)
    print("NAS_STATUS",n,enum(v,{"OK","ERROR","RUNNING","DEGRADED","VIDEO","ALERTS","CONTENT","host_autodeploy_failed","IDLE","DONE"}),flush=True)

print("=== ADMIN HTTP, SAFE ERROR CLASSIFICATION ===",flush=True)
url=getfile(R/"RG_NAS_CONTROL/admin_url",2048)
token=getfile(R/"RG_SECRETS/rg_admin_token",4096)
if not url or not token:print("ADMIN_CONFIG MISSING");sys.exit(1)
p=urlsplit(url)
if (p.scheme not in ("https","http") or not p.hostname or p.username or p.password or p.query or p.fragment
        or (p.scheme=="http" and p.hostname not in ("127.0.0.1","localhost"))):
    print("ADMIN_URL INVALID");sys.exit(1)
if not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",token):
    print("ADMIN_TOKEN INVALID_FORMAT");sys.exit(1)
curl=shutil.which("curl")
if not curl: print("CURL MISSING");sys.exit(1)
cfg='header = "Authorization: Bearer '+token+'"\nconnect-timeout = 8\nmax-time = 20\n'
def get(path):
    try:
        cp=subprocess.run([curl,"--silent","--show-error","--config","-",
          "--max-filesize","8000000","--write-out","\nRG_CODE:%{http_code}",
          url.rstrip("/")+path],input=cfg.encode(),capture_output=True,timeout=25)
        mark=b"\nRG_CODE:"
        if mark not in cp.stdout:return "UNKNOWN",{}
        content,code=cp.stdout.rsplit(mark,1)
        code=code.strip().decode("ascii","replace")
        return code,ob(json.loads(content))
    except Exception:return "UNKNOWN",{}
http,s=get("/status")
print("HTTP_STATUS",http)
mod=ob(ob(s.get("state")).get("telegram-video-moderation-health-v2"))
print("MODERATION","ok",bo(mod.get("ok")),"degraded",bo(mod.get("degraded")),
      "reason",enum(mod.get("degradedReason"),{"broken_moderation_card_recovery","legacy_placeholder_cleanup","moderation_card_cleanup"}),
      "updatesFailed",number(mod.get("updatesFailed")),
      "offsetBlocked",bo(mod.get("offsetBlocked")))
broken=ob(mod.get("brokenCardRecovery"))
print("BROKEN_CARD_RECOVERY","ran",bo(broken.get("ran")),"error_class",classify_error(broken.get("error")),
      "error_present",bo(bool(broken.get("error"))),"fixed",number(broken.get("fixed")),
      "scanned",number(broken.get("scanned")))
placeholder=ob(mod.get("placeholderCleanup"));card=ob(mod.get("cardCleanup"))
print("CARD_CLEANUP","ok",bo(card.get("ok")),"placeholderError",bo(bool(placeholder.get("error"))),
      "brokenCardError",bo(bool(broken.get("error"))))
print("PUBLISH_QUEUE","ok",bo(ob(mod.get("publicationQueue")).get("ok")),
      "verifyOk",bo(ob(mod.get("publicationVerify")).get("ok")))
code,pdoc=get("/production-state")
print("HTTP_PRODUCTION_STATE",code,"json",bo(bool(pdoc)))
print("PRODUCTION_BODY","ok",bo(pdoc.get("ok")),"error_class",classify_error(pdoc.get("error")),
      "error_present",bo(bool(pdoc.get("error"))))
code,ndoc=get("/nas-health-public")
print("HTTP_NAS_HEALTH",code,"sync",bo(ndoc.get("synced")),
      "commandBusSyntaxOk",bo(ob(ndoc.get("commandBus")).get("syntaxOk")))

print("=== AUTO DEPLOY RECENT MISSING PATH SUMMARY ===",flush=True)
log=S/"auto-deploy.log"
if log.is_file() and not log.is_symlink():
    with log.open("r",errors="replace") as f:
        from collections import deque
        tail=list(deque(f,maxlen=400))
    kinds=collections.Counter()
    names=collections.Counter()
    for line in tail:
        low=line.lower()
        if "no such file" in low: kind="NO_SUCH_FILE"
        elif "cannot stat" in low:kind="CANNOT_STAT"
        elif "not found" in low:kind="NOT_FOUND"
        elif "missing" in low:kind="MISSING_OTHER"
        else:continue
        kinds[kind]+=1
        for m in re.findall(r"/[A-Za-z0-9_./-]+",line):
            b=m.rstrip("/").split("/")[-1]
            if len(b)<3 or len(b)>80 or re.search("token|secret|passwd|password|credential",b,re.I):continue
            if re.fullmatch(r"[A-Za-z0-9_.-]+",b):
                names[b]+=1
    print("LOG_SCAN_LINES",len(tail))
    print("MISSING_CATEGORIES",json.dumps(kinds,sort_keys=True))
    print("MISSING_BASENAME_TOP",json.dumps(names.most_common(12)))
else:
    print("LOG_NOT_AVAILABLE")
print("RG_TELEGRAM_V4: DONE")
PY
