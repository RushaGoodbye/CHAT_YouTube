#!/bin/sh
# Inspect Synology task registration WITHOUT running tasks or changing services.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "ERROR: requires sudo sh"; exit 2; }
python3 - <<'PY'
import os
import re
import subprocess
import time
from pathlib import Path

print("=== RG TELEGRAM SCHEDULER REGISTRATION V3 (READ ONLY) ===", flush=True)
ROOT=Path("/volume1/docker")
S=ROOT/"RG_NAS_STATE"
CLI="/usr/syno/bin/synoschedtask"
NAMES=("RG_NAS_SCHEDULER_TICK.sh","RG_NAS_AUTO_DEPLOY.sh","RG_NAS_TELEGRAM_WATCHDOG.sh")
SENSITIVE=re.compile(r"(token|secret|password|bearer|authorization|sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{8,})",re.I)
RELEVANT=re.compile(r"RG_NAS|TELEGRAM|WATCHDOG|AUTO.?DEPLOY|SCHEDULER",re.I)
FIELD=re.compile(r"(?:^|\s)(?:id|task\s*id|name|owner|user|enabled?|state|status|schedule|time|day|week|month|minute|hour|command|script|task|period|type|interval|next|start)(?:\s|:|=)",re.I)
def safe(text,n=180):
    text=text.strip().replace("\r","")
    if SENSITIVE.search(text):return "[FILTERED_SENSITIVE_FIELD]"
    return "".join(ch for ch in text if ch.isprintable())[:n]
def readstatus(name):
    p=S/name
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size>512: return "MISSING_OR_UNSAFE"
        return safe(p.read_text(encoding="utf-8",errors="replace"),80)
    except OSError:return "MISSING"
print("=== SCRIPT VALIDATION ===")
for name in NAMES:
    p=ROOT/name
    if not p.is_file() or p.is_symlink():
        print("SCRIPT",name,"MISSING");continue
    b=p.read_bytes()
    try:
        res=subprocess.run(["/bin/sh","-n",str(p)],capture_output=True,timeout=8)
        code=res.returncode
    except Exception:
        code=-1
    print("SCRIPT",name,"syntax","PASS" if code==0 else "ERROR","crlf_count",b.count(b"\r\n"),"executable",bool(p.stat().st_mode&0o111))
print("=== SYNOSCHEDTASK --get ===")
if not Path(CLI).is_file():
    print("TASK_CLI_NOT_FOUND")
else:
    try:
        p=subprocess.run([CLI,"--get"],capture_output=True,text=True,errors="replace",timeout=20)
        print("GET_EXIT_CODE",p.returncode,"TOTAL_LINES",len(p.stdout.splitlines()))
        if p.returncode:
            print("GET_ERROR",safe(p.stderr,180))
        else:
            lines=p.stdout.splitlines()
            matches=[i for i,s in enumerate(lines) if RELEVANT.search(s)]
            print("RELEVANT_LINE_COUNT",len(matches))
            nearby=set()
            for i in matches:
                # Include adjacent task metadata without printing arbitrary command arguments.
                for j in range(max(0,i-7),min(len(lines),i+10)):
                    nearby.add(j)
            for i in sorted(nearby):
                s=lines[i]
                if not s.strip():continue
                if not (FIELD.search(s) or RELEVANT.search(s)):continue
                label=("MATCH" if i in matches else "CONTEXT")
                if SENSITIVE.search(s):
                    shown="[FILTERED_SENSITIVE_FIELD]"
                elif re.search(r"(?i)\b(command|script|task)\s*[:=]",s):
                    found=sorted(set(re.findall(r"RG_[A-Z0-9_]+\.sh",s,re.I)))
                    shown="COMMAND_TARGETS="+(",".join(found) if found else "NOT_RECOGNIZED")
                else:
                    shown=safe(s)
                print("TASK_LINE",i+1,label,shown)
    except Exception as e:
        print("GET_EXCEPTION",type(e).__name__)
print("=== ACTIVE PROCESS COUNTS ===")
proc=Path("/proc")
for name in ("RG_NAS_SCHEDULER_TICK.sh","RG_NAS_AUTO_DEPLOY.sh","RG_NAS_TELEGRAM_WATCHDOG.sh","RG_NAS_AUTODEPLOY_LOOP.sh"):
    ids=[]
    for p in proc.iterdir():
        if not p.name.isdigit():continue
        try:
            b=(p/"cmdline").read_bytes()
            if name.encode() in b and b"\x00python3\x00" not in b:
                # Only print count: never expose full process command lines.
                ids.append(p.name)
        except (OSError,PermissionError):continue
    print("PROCESS",name,"count",len(ids))
print("=== CURRENT HEARTBEATS ===")
for name in ("scheduler_last_check_at","scheduler_last_check_status","scheduler_dispatch_error",
             "scheduler_dispatch_ok_at","telegram_watchdog_status","telegram_control_plane_status"):
    p=S/name
    try:
        age=max(0,int(time.time()-p.stat().st_mtime))
        print("HEARTBEAT",name,"age_sec",age,"value",readstatus(name))
    except OSError:print("HEARTBEAT",name,"MISSING")
print("RG_TELEGRAM_SCHEDULE_DIAG: DONE_READ_ONLY")
PY
