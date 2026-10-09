#!/bin/sh
# V8: sanitize and summarize the EXISTING Alerts Worker deploy error.
# Read-only: no container actions, service changes or Telegram requests.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Use sudo sh"; exit 2; }
python3 - <<'PY'
import collections,datetime,re,time
from pathlib import Path
D=Path("/volume1/docker/RG_NAS_STATE")
P=D/"last-alerts-deploy.log"
AUTO=D/"auto-deploy.log"
print("=== RG TELEGRAM ALERTS DEPLOY FAILURE V8 (READ ONLY) ===",flush=True)
print("LOCAL_TIME",datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
def load(p,n=200):
    if p.is_symlink() or not p.is_file() or p.stat().st_size>5000000:return [],None
    try:
        with p.open("r",errors="replace") as f:
            arr=list(collections.deque(f,maxlen=n))
        age=max(0,int(time.time()-p.stat().st_mtime))
        return arr,age
    except OSError:return [],None
def scrub(s):
    s=re.sub(r"\x1b\[[0-9;]*[A-Za-z]","",s)
    s="".join(c for c in s if c.isprintable())
    if re.search(r"(?i)authorization|bearer|api[_-]?key|secret|password|access[_-]?token|account[_-]?token|user[_-]?token",s):
        return "[SENSITIVE_LINE_OMITTED]"
    s=re.sub(r"(?i)(?:https?|wss?)://\S+","[URL]",s)
    s=re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b","[EMAIL]",s)
    s=re.sub(r"\b[0-9a-fA-F]{32,}\b","[HEX_ID]",s)
    s=re.sub(r"(?<![A-Za-z0-9_])[A-Za-z0-9_+/=-]{26,}(?![A-Za-z0-9_])","[LONG_ID]",s)
    s=re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b","[IP]",s)
    s=re.sub(r"/(?:volume1|home|root|Users)/\S+","[LOCAL_PATH]",s)
    return s[:195] if s.strip() else "[EMPTY]"
rows,age=load(P,150)
print("ALERT_ERROR_LOG","lines",len(rows),"age_sec",age if age is not None else "UNKNOWN")
if rows:
    # De-dupe text and retain meaningful headings near the failure.
    scored=[]
    for i,line in enumerate(rows,1):
        raw=line.strip()
        if not raw:continue
        s=scrub(raw)
        if s=="[SENSITIVE_LINE_OMITTED]":continue
        high=bool(re.search(r"(?i)error|failed|fatal|unknown|code\b|npm err|e(?:invalid|access|resolve|noent|conn)|wrangler|upload|compil|binding|migration|asset|unsupported|incompatible|missing|required|^✘|^×|^×",s))
        if high:
            scored.append((i,s))
    count=collections.Counter(x for _,x in scored)
    # Print first 10 distinct error lines plus last 14, no more than 22.
    selected={}
    for i,s in scored[:10]+scored[-30:]:
        if s not in selected:selected[s]=i
    for s,i in list(selected.items())[-22:]:
        print("SAFE_ERROR_LINE","line",i,"repeats",count[s],"text",s,flush=True)
    print("UNIQUE_ERROR_TYPES",len(count),"TOTAL_MARKED_LINES",len(scored),flush=True)
arows,aage=load(AUTO,160)
print("AUTO_LOG","lines_read",len(arows),"age_sec",aage if aage is not None else "UNKNOWN")
for i,line in enumerate(arows[-80:],1):
    tag=None
    if re.search(r"(?i)alerts deploy container exited with code",line):tag="ALERTS_EXIT_NONZERO"
    elif re.search(r"(?i)Alert Worker deploy failed",line):tag="ALERTS_FAILED"
    elif re.search(r"(?i)Starting alerts deploy container",line):tag="ALERTS_STARTED"
    elif re.search(r"(?i)ROLLBACK completed with errors",line):tag="ROLLBACK_ERROR"
    elif re.search(r"(?i)ROLLBACK completed$",line.strip()):tag="ROLLBACK_OK"
    elif re.search(r"(?i)RG_NAS_DEPLOY_OK",line):tag="DEPLOY_OK"
    if tag:print("DEPLOY_EVENT",i,tag,flush=True)
print("RG_TELEGRAM_V8_COMPLETE_NO_WRITES",flush=True)
PY
