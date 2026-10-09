#!/bin/sh
# RG Telegram one-shot failure evidence V7. READ-ONLY: no deploys, queue reads,
# moderation decisions, restarts, Telegram API calls or config changes.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Requires sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,json,os,re,shutil,subprocess,time
from pathlib import Path
R=Path("/volume1/docker")
S=R/"RG_NAS_STATE"
print("=== RG TELEGRAM V7 DEPLOY FAILURE EVIDENCE - READ ONLY ===",flush=True)
def age(p):
    try:return max(0,int(time.time()-p.stat().st_mtime))
    except OSError:return "UNKNOWN"
def read(p,limit=250):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return ""
        return p.read_text(encoding="utf-8",errors="replace").strip()
    except OSError:return ""
def statval(name):
    v=read(S/name)
    vals={"OK","ERROR","RUNNING","DEPLOYING","DEGRADED","VIDEO","ALERTS","CONTENT","LIVE_SMOKE","PREPARE","COMPLETE","CONTROL_PLANE","SYNCED","IDLE","host_autodeploy_failed"}
    return v if v in vals else ("ABSENT" if not v else "OTHER")
def error_groups(line):
    patterns=[
    ("npm_install",r"(?i)npm (?:err|error)|npm install|npm ci|npm warn"),
    ("npm_dependency",r"(?i)cannot find module|module not found|eresolve|enoent|package-lock"),
    ("worker_compile",r"(?i)build failed|syntaxerror|could not resolve|bundl|failed to compile"),
    ("wrangler_deploy",r"(?i)wrangler deploy|deployment failed|publishing|upload failed"),
    ("cf_api_auth",r"(?i)cloudflare.*(?:401|403|unauthorized)|error code.*(?:10000|10001|10002)"),
    ("cf_api_bad_request",r"(?i)(cloudflare|wrangler).*(?:400|invalid.*binding|invalid.*route)"),
    ("cf_api_rate",r"(?i)(429|rate limit|too many requests)"),
    ("cf_api_quota",r"(?i)(limit exceeded|quota exceeded|script too large|exceeded maximum)"),
    ("permission",r"(?i)permission denied|eacces|eperm"),
    ("network",r"(?i)etimedout|econnreset|network error|fetch failed|connection refused|could not resolve|tls|certificate|socket hang up"),
    ("docker_oom",r"(?i)out of memory|oomkill|killed process|exit code 137"),
    ("file_missing",r"(?i)no such file|cannot stat|not found"),
    ("http_403",r"(?i)\b403\b|forbidden"),
    ("http_503",r"(?i)\b503\b|service unavailable"),
    ("http_500",r"(?i)\b500\b|internal server error"),
    ("error_generic",r"(?i)\berror\b|\bfailed\b"),
    ]
    return [k for k,rx in patterns if re.search(rx,line)]
def tail_lines(p,count,limit=20000000):
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:return None
        with p.open(encoding="utf-8",errors="replace") as f:
            return list(collections.deque(f,maxlen=count))
    except (OSError,UnicodeError):return None
for name in ("scheduler_last_check_status","scheduler_dispatch_error","last_deploy_status","deploy_stage","deploy_sync_status","last_video_deploy_status","last_alerts_deploy_status","last_content_deploy_status","rollback_status","live_smoke_status"):
    p=S/name
    v=read(p,150)
    if name.startswith("last_") and name.endswith("_deploy_status") and re.fullmatch(r"ERROR (?:code=\d+|timeout)",v):
        value=v
    else:value=statval(name)
    print("STATE",name,value,"age_seconds",age(p),flush=True)
print("=== DEPLOY CONTAINERS (READ ONLY) ===",flush=True)
docker=next((x for x in ["/usr/local/bin/docker","/usr/bin/docker"] if os.path.isfile(x)),None)
if docker:
    for name in ("rg-deploy-deploy-1","rg-alerts-deploy-deploy-1","rg-content-deploy-deploy-1"):
        try:
            c=subprocess.run([docker,"inspect","--format","{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.RestartCount}}",name],
                             capture_output=True,text=True,timeout=8)
            raw=c.stdout.strip()
            if c.returncode==0 and re.fullmatch(r"(?:running|exited|created|dead|restarting)\|\d+\|(?:true|false)\|\d+",raw):
                print("DOCKER",name,raw)
            else: print("DOCKER",name,"UNKNOWN_OR_NOT_FOUND")
        except Exception:
            print("DOCKER",name,"UNKNOWN")
else: print("DOCKER_CLI_UNAVAILABLE")
print("=== COMPONENT ERROR LOGS ===",flush=True)
for logname in ("last-video-deploy.log","last-alerts-deploy.log","last-content-deploy.log",
                "last-rollback-video.log","last-rollback-alerts.log","last-rollback-content.log",
                "admin-control.log","admin-control-rollback.log"):
    p=S/logname
    rows=tail_lines(p,200)
    if rows is None:
        print("LOG",logname,"UNAVAILABLE");continue
    subset=[(i+1,error_groups(x)) for i,x in enumerate(rows) if error_groups(x)]
    bycat=collections.Counter(cat for _,categories in subset for cat in categories)
    last=subset[-8:]
    print("LOG",logname,"age_seconds",age(p),"bytes",p.stat().st_size,
          "tail_lines",len(rows),"matches",len(subset),"categories",
          json.dumps(dict(bycat.most_common(12)),sort_keys=True))
    for lineno,categories in last:
        # Never print the raw lines: worker deployment logs may expose credentials.
        print("LOG_HIT",logname,"tail_line",lineno,"categories",",".join(categories),flush=True)
print("=== AUTO-DEPLOY STATE TRANSITIONS ===",flush=True)
p=S/"auto-deploy.log";rows=tail_lines(p,400)
if rows is not None:
    patterns=[
      ("start_video",r"(?i)Starting video deploy container"),
      ("start_alerts",r"(?i)Starting alerts deploy container"),
      ("start_content",r"(?i)Starting content deploy container"),
      ("exit_code",r"(?i)deploy container exited with code"),
      ("deploy_timeout",r"(?i)deploy timed out after"),
      ("rollback_start",r"(?i)ROLLBACK starting$"),
      ("rollback_finished",r"(?i)ROLLBACK completed(?: with errors)?$"),
      ("rollback_component",r"(?i)ROLLBACK (?:video|alerts|content) (?:completed|exited|timed out)"),
      ("general_error",r"(?i)\bERROR:"),
      ("deploy_success",r"RG_NAS_DEPLOY_OK"),
    ]
    for i,line in enumerate(rows[-120:],1):
        tags=[k for k,rx in patterns if re.search(rx,line.strip())]
        if tags:
            print("TRANSITION","last120_line",i,"type",",".join(tags),flush=True)
    print("AUTO_LOG_LAST_CHANGE_AGE_SEC",age(p))
else:print("AUTO_DEPLOY_LOG_UNAVAILABLE")
print("RG_TELEGRAM_V7_EVIDENCE_COMPLETE - NO CHANGES",flush=True)
PY
