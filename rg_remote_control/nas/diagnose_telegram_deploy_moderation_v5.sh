#!/bin/sh
# RG Telegram V5 root-cause probe. Read-only; no write, restart, queue or publish actions.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Requires: sudo sh"; exit 2; }
python3 - <<'PY'
import collections, datetime, json, re, shutil, subprocess, time
from pathlib import Path
from urllib.parse import urlsplit
R=Path("/volume1/docker"); S=R/"RG_NAS_STATE"
print("=== RG TELEGRAM HTTP403 + AUTO DEPLOY V5 - READ ONLY ===",flush=True)
print("LOCAL_TIME",datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
def read(p,cap=4096):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>cap:return None
        return p.read_text(encoding="utf8",errors="replace").strip()
    except OSError:return None
def bo(v):return "TRUE" if v is True else "FALSE" if v is False else "UNKNOWN"
def age(p):
    try:return max(0,int(time.time()-p.stat().st_mtime))
    except OSError:return "UNKNOWN"
def classify(s):
    if not isinstance(s,str) or not s:return "NONE"
    m=re.search(r"\b(?:HTTP|status)\s*(\d{3})\b",s,re.I)
    if m:return "HTTP_"+m.group(1)
    groups=[
      ("file_missing",r"no such file|file not found|not found|cannot stat"),
      ("permission",r"permission denied|forbidden|access denied"),
      ("authentication",r"unauthorized|authentication failed"),
      ("timeout",r"timed out|timeout|deadline"),
      ("rate_limit",r"too many requests|rate.?limit|quota"),
      ("network",r"connect.*fail|dns|resolve|network"),
      ("syntax",r"syntax error|bad interpreter|invalid syntax"),
      ("storage",r"durable|storage|kv"),
    ]
    for key,pattern in groups:
        if re.search(pattern,s,re.I):return key.upper()
    return "OTHER"
def value(s,allow):
    return s if s in allow else "OTHER_OR_UNKNOWN"
for name in ("scheduler_last_check_status","last_deploy_status","deploy_stage","scheduler_dispatch_error","telegram_control_plane_status","telegram_watchdog_status","live_smoke_status","last_error","live_smoke_error"):
    p=S/name;raw=read(p,1000)
    output=classify(raw) if name in ("last_error","live_smoke_error") else value(raw,{"OK","ERROR","RUNNING","DEGRADED","VIDEO","ALERTS","CONTENT","host_autodeploy_failed","IDLE"})
    print("STATE",name,"age_sec",age(p),"value",output,flush=True)
for name in ("RG_NAS_SCHEDULER_TICK.sh","RG_NAS_AUTO_DEPLOY.sh","RG_NAS_TELEGRAM_WATCHDOG.sh","RG_NAS_COMMAND_BUS.sh"):
    p=R/name
    if not p.is_file() or p.is_symlink():
        print("SCRIPT",name,"MISSING_OR_SYMLINK");continue
    data=p.read_bytes()
    test=subprocess.run(["/bin/sh","-n",str(p)],capture_output=True,timeout=12)
    print("SCRIPT",name,"CRLF",data.count(b"\r\n"),"SYNTAX",("PASS" if test.returncode==0 else "ERROR"),"age_sec",age(p),flush=True)

print("=== LAST AUTO DEPLOY LOG (CATEGORIES ONLY) ===",flush=True)
log=S/"auto-deploy.log"
if log.is_file() and not log.is_symlink() and log.stat().st_size<40000000:
    with log.open(encoding="utf-8",errors="replace") as stream:
        from collections import deque
        rows=list(deque(stream,maxlen=500))
    for scope,count in [("last30",30),("last100",100),("last500",500)]:
        segment=rows[-count:]
        missing=[x for x in segment if ("no such file" in x.lower() or "not found" in x.lower())]
        auto_missing=[x for x in missing if "RG_NAS_AUTO_DEPLOY.sh" in x]
        print("LOG",scope,"lines",len(segment),"missing",len(missing),"auto_deploy_script_missing",len(auto_missing),flush=True)
    print("LOG_FILE_AGE_SEC",age(log),"LOG_FILE_BYTES",log.stat().st_size,flush=True)
    for offset,line in enumerate(rows[-30:],start=1):
        if "RG_NAS_AUTO_DEPLOY.sh" in line or "No such file" in line:
            tags=[]
            for t in ("bash","sh:","No such file","bad interpreter","syntax error","RG_NAS_AUTO_DEPLOY.sh","CRLF"):
                if t.lower() in line.lower():tags.append(t.replace(" ","_"))
            print("RECENT_LOG_MATCH","line_in_last30",offset,"tags",",".join(tags),flush=True)
else:print("LOG MISSING_OR_TOO_LARGE",flush=True)

print("=== INTERNAL COORDINATOR READ-ONLY PROBES ===",flush=True)
admin=read(R/"RG_NAS_CONTROL/admin_url",1024)
token=read(R/"RG_SECRETS/rg_admin_token",4096)
if not admin or not token:
    print("ADMIN_CONFIG_INCOMPLETE");raise SystemExit(1)
p=urlsplit(admin)
if (p.scheme not in ("https","http") or not p.hostname or p.username or p.password or p.query or p.fragment
    or (p.scheme=="http" and p.hostname not in ("localhost","127.0.0.1")) or not re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,4096}",token)):
    print("ADMIN_CONFIG_UNEXPECTED");raise SystemExit(1)
curl=shutil.which("curl")
if not curl:
    print("CURL_NOT_FOUND");raise SystemExit(1)
# credentials are passed over stdin and NEVER printed or added to curl argv.
cfg='header = "Authorization: Bearer '+token+'"\nconnect-timeout = 8\nmax-time = 18\n'
def probe(endpoint):
    try:
        r=subprocess.run([curl,"--silent","--show-error","--config","-","--max-filesize","6000000",
           "--write-out","\nRG_HTTP=%{http_code}",admin.rstrip("/")+endpoint],
           input=cfg.encode(),capture_output=True,timeout=23,check=False)
        mark=b"\nRG_HTTP="
        if mark not in r.stdout:return "UNKNOWN",{},r.returncode
        raw,code=r.stdout.rsplit(mark,1)
        code=code.decode("ascii","replace").strip()
        if code not in ("200","401","403","404","429","500","502","503","504"):code="OTHER"
        try: doc=json.loads(raw)
        except (ValueError,UnicodeError):doc={}
        return code,doc if isinstance(doc,dict) else {},r.returncode
    except Exception:return "ERROR",{},-1
for endpoint in ("/moderation-candidates?limit=1","/production-state","/nas-health-public"):
    code,body,rc=probe(endpoint)
    print("HTTP",endpoint,"code",code,"curl_exit",rc,"json_keys",",".join(sorted(k for k in body if k in ("ok","error","message","status","items","productionReadiness","deploy","liveSmoke","count"))),flush=True)
    if endpoint.startswith("/moderation-candidates"):
        print("MODERATION_CANDIDATES_API","ok",bo(body.get("ok")),"error_category",classify(body.get("error")),flush=True)
    if endpoint=="/production-state":
        print("PRODUCTION_SNAPSHOT","ok",bo(body.get("ok")),"has_readiness",bo(isinstance(body.get("productionReadiness"),dict)),"error_category",classify(body.get("error")),flush=True)
    if endpoint=="/nas-health-public":
        print("NAS_DEPLOY","status",value(body.get("status"),{"OK","ERROR","DEPLOYING","DEGRADED","RUNNING","IDLE"}),"synced",bo(body.get("synced")),"syntax",bo((body.get("commandBus") or {}).get("syntaxOk") if isinstance(body.get("commandBus"),dict) else None),flush=True)
print("RG_TELEGRAM_V5: DONE_READ_ONLY",flush=True)
PY
