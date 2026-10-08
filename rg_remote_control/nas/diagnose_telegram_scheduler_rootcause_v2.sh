#!/bin/sh
# Read-only Synology Scheduler + Telegram probe; no writes or service restarts.
set -u
echo "=== RG TELEGRAM ROOT CAUSE V2: READ-ONLY ==="
if [ "$(id -u)" -ne 0 ]; then echo "Requires: sudo sh"; exit 2; fi
python3 - <<'PY'
import json, re, shutil, subprocess, time, urllib.request
from pathlib import Path

root=Path("/volume1/docker")
state=root/"RG_NAS_STATE"
scripts=[
"RG_NAS_SCHEDULER_TICK.sh",
"RG_NAS_AUTO_DEPLOY.sh",
"RG_NAS_TELEGRAM_WATCHDOG.sh",
"RG_NAS_TELEGRAM_CONTROL_PLANE.sh",
"RG_TELEGRAM_CONTROL_AGENT.sh",
"RG_NAS_MCP_TICK.sh",
]
def clean(s,limit=380):
    s=str(s).replace("\n"," ").replace("\r"," ")
    s=re.sub(r"(?i)(sk-[a-z0-9_-]{8,}|gh[pousr]_[a-z0-9_]{8,}|bearer\s+\S+|password\s*[=:]\s*\S+|token\s*[=:]\s*\S+)","[REDACTED]",s)
    return "".join(ch if ch.isprintable() else " " for ch in s)[:limit]
def cmd(args,timeout=10):
    try:
        p=subprocess.run(args,capture_output=True,text=True,errors="replace",timeout=timeout)
        return p.returncode,p.stdout,p.stderr
    except Exception as e:
        return -1,"",type(e).__name__
print("NAS_TIME",time.strftime("%Y-%m-%dT%H:%M:%S%z"))
try: print("UPTIME_SEC",int(float(Path("/proc/uptime").read_text().split()[0])))
except Exception: print("UPTIME UNKNOWN")
print("=== SCRIPT SYNTAX ===")
for name in scripts:
    p=root/name
    if not p.is_file():
        print("SCRIPT",name,"NOT_FOUND");continue
    b=p.read_bytes()
    print("SCRIPT",name,"bytes",len(b),"crlf",b.count(b"\r\n"),"nul",b.count(b"\x00"),
          "shebang",clean(b.split(b"\n",1)[0].decode("utf-8","replace"),80))
    for shell in ["sh","bash"]:
        if not shutil.which(shell): continue
        code,out,err=cmd([shell,"-n",str(p)],6)
        print("SYNTAX",name,shell,"exit",code,"error",clean(err) if code else "NONE")
print("=== SCHEDULE REGISTRATION ===")
binary=shutil.which("synoschedtask")
if not binary:
    binary=next((str(x) for x in [Path("/usr/syno/bin/synoschedtask"),Path("/usr/syno/sbin/synoschedtask")] if x.is_file()),None)
if binary:
    code,out,err=cmd([binary,"--enum"],12)
    print("SYNOSCHED_ENUM exit",code,"lines",len(out.splitlines()),"error",clean(err,180))
    pattern=re.compile("rg|telegram|watchdog|scheduler|auto.deploy|auto_deploy",re.I)
    rows=[(i,line) for i,line in enumerate(out.splitlines(),1) if pattern.search(line)]
    print("SYNOSCHED_MATCH_COUNT",len(rows))
    for index,line in rows[:25]:
        terms=sorted(set(x.lower() for x in pattern.findall(line)))
        print("SYNOSCHED_MATCH row",index,"terms",",".join(terms))
else:
    print("SYNOSCHEDTASK_CLI NOT_FOUND")
for path in [Path("/etc/crontab"),Path("/var/spool/cron/crontabs/root"),Path("/var/spool/cron/root"),Path("/usr/syno/etc/synoschedtask.conf")]:
    if path.is_file() and path.stat().st_size<1000000:
        lines=path.read_text(errors="replace").splitlines()
        matches=sum(bool(re.search("RG_NAS_SCHEDULER_TICK|RG_NAS_AUTO_DEPLOY|RG_NAS_TELEGRAM_WATCHDOG",s,re.I)) for s in lines)
        print("SCHEDULE_FILE",str(path),"matching_lines",matches)
print("=== CONTAINER AND HEALTH ===")
docker=next((str(p) for p in [Path("/usr/local/bin/docker"),Path("/usr/bin/docker"),Path("/var/packages/ContainerManager/target/usr/bin/docker")] if p.is_file()),None)
ports=[]
if docker:
    for name in ["rg-telegram-control","rg-nas-mcp-hub","rg-openai-tunnel-telegram-readonly"]:
        code,out,err=cmd([docker,"inspect","-f","{{.State.Status}}",name])
        print("CONTAINER",name,clean(out.strip(),80) if code==0 else "NOT_FOUND")
    code,out,err=cmd([docker,"port","rg-telegram-control","8788/tcp"])
    if code==0:
        print("CONTROL_APP_PUBLISHED_PORTS",clean(out,160))
        for line in out.splitlines():
            m=re.search(r":(\d+)\s*$",line)
            if m: ports.append(m.group(1))
p=state/"rg_telegram_control_app_port"
if p.is_file() and p.stat().st_size<16:
    port=p.read_text(errors="replace").strip()
    if port.isdigit(): ports.insert(0,port)
print("CONTROL_APP_PORTS_TO_TEST",",".join(dict.fromkeys(ports)) or "UNKNOWN")
for port in dict.fromkeys(ports):
    try:
        if not 1<=int(port)<=65535: continue
        with urllib.request.urlopen("http://127.0.0.1:"+port+"/healthz",timeout=4) as res:
            code=res.status; body=res.read(16000)
        d=json.loads(body)
        print("CONTROL_APP_HEALTH port",port,"HTTP",code,"ok",d.get("ok"),
              "ready",d.get("ready"),"version",clean(d.get("version"),40),
              "snapshot_fresh",(d.get("snapshot") or {}).get("fresh") if isinstance(d.get("snapshot"),dict) else "UNKNOWN")
    except Exception as e:
        print("CONTROL_APP_HEALTH port",port,"ERROR",clean(type(e).__name__+": "+str(e),170))
print("=== SNAPSHOT AGE ===")
for name in ["scheduler_last_check_at","scheduler_last_check_status","scheduler_dispatch_error",
"telegram_watchdog_status","telegram_control_plane_status","rg_telegram_control_app_status"]:
    p=state/name
    if not p.is_file() or p.stat().st_size>512: print("STATE",name,"MISSING_OR_LARGE");continue
    value=p.read_text(errors="replace").strip()
    if re.search("token|secret|password|bearer",value,re.I):value="[REDACTED]"
    print("STATE",name,"age_sec",max(0,int(time.time()-p.stat().st_mtime)),"value",clean(value,90))
print("=== DONE: NO SERVICES OR SETTINGS MODIFIED ===")
PY
