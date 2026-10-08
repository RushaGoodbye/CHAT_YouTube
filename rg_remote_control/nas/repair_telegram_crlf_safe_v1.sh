#!/bin/sh
# RG Telegram: repair ONLY three known CRLF-corrupted NAS shell scripts.
# No scripts are executed. No Docker containers, schedules or queues are modified.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "ERROR: Requires sudo sh"; exit 2; }
python3 - <<'PY'
import datetime
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path("/volume1/docker")
state = root / "RG_NAS_STATE"
names = (
    "RG_NAS_SCHEDULER_TICK.sh",
    "RG_NAS_AUTO_DEPLOY.sh",
    "RG_NAS_TELEGRAM_WATCHDOG.sh",
)
print("=== RG TELEGRAM CRLF REPAIR V1 ===", flush=True)
plan = []
errors = []
for name in names:
    path = root / name
    if path.is_symlink() or not path.is_file():
        errors.append(f"{name}: missing file or symlink")
        continue
    before = path.read_bytes()
    fixed = before.replace(b"\r\n", b"\n")
    if b"\r" in fixed:
        errors.append(f"{name}: unexpected bare CR byte, not safe to normalize")
        continue
    if not fixed.startswith(b"#!/bin/sh\n"):
        errors.append(f"{name}: unexpected shebang or first line")
        continue
    for shell in ("/bin/sh", shutil.which("bash")):
        if not shell:
            continue
        test = subprocess.run([shell, "-n"], input=fixed,
                              capture_output=True, timeout=15)
        if test.returncode:
            msg = test.stderr.decode("utf-8", "replace").strip().replace("\n", " ")[:280]
            errors.append(f"{name}: {shell} syntax fails after normalization: {msg}")
            break
    if errors:
        continue
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        errors.append(f"{name}: not a regular file")
        continue
    old_hash = hashlib.sha256(before).hexdigest()
    print(f"PREFLIGHT {name}: CRLF={before.count(bytes([13,10]))} bytes={len(before)} sha256={old_hash[:16]} syntax_after=PASS",flush=True)
    plan.append((name,path,before,fixed,info))
if errors or len(plan)!=len(names):
    for reason in errors:
        print("REFUSED", reason,flush=True)
    print("ABORTED: no files modified",flush=True)
    sys.exit(1)
changes=[item for item in plan if item[2]!=item[3]]
if not changes:
    print("ALREADY_FIXED: all three scripts have LF and pass sh -n",flush=True)
else:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir=state / "telegram_crlf_backups" / stamp
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    backup_dir.chmod(0o700)
    for name,path,before,fixed,info in changes:
        destination=backup_dir/(name+".bak")
        with destination.open("xb") as stream:
            stream.write(before)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(destination,0o600)
        if destination.read_bytes()!=before:
            print("BACKUP FAILED for",name,": no changes made",flush=True)
            sys.exit(1)
    print("BACKUP_COMPLETE path="+str(backup_dir),flush=True)
    updated=[]
    try:
        for name,path,before,fixed,info in changes:
            fd, temp_path=tempfile.mkstemp(prefix="."+name+".lf.",dir=str(root))
            try:
                with os.fdopen(fd,"wb") as out:
                    out.write(fixed)
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(temp_path, stat.S_IMODE(info.st_mode))
                os.chown(temp_path, info.st_uid, info.st_gid)
                # Refuse changes if another job altered the source since preflight.
                if path.read_bytes()!=before:
                    raise RuntimeError(name+": source changed during repair")
                os.replace(temp_path,path)
                updated.append((name,path))
            finally:
                if os.path.exists(temp_path): os.unlink(temp_path)
        for name,path,before,fixed,info in changes:
            if path.read_bytes()!=fixed:
                raise RuntimeError(name+": post-write mismatch")
            result=subprocess.run(["/bin/sh","-n",str(path)],capture_output=True,timeout=15)
            if result.returncode:
                raise RuntimeError(name+": post-write syntax failed")
            print("FIXED",name,"LF_ONLY=YES syntax=PASS",flush=True)
    except Exception as exc:
        print("REPAIR_ERROR",str(exc)[:220],flush=True)
        print("ROLLBACK: restoring files changed by this run",flush=True)
        for name,path in reversed(updated):
            saved=backup_dir/(name+".bak")
            try:
                data=saved.read_bytes()
                info=next(row[4] for row in changes if row[0]==name)
                fd,tmp=tempfile.mkstemp(prefix="."+name+".restore.",dir=str(root))
                with os.fdopen(fd,"wb") as out:
                    out.write(data);out.flush();os.fsync(out.fileno())
                os.chmod(tmp,stat.S_IMODE(info.st_mode))
                os.chown(tmp,info.st_uid,info.st_gid)
                os.replace(tmp,path)
                print("RESTORED",name,flush=True)
            except Exception as rollback_exc:
                print("MANUAL_RESTORE_NEEDED",name,str(rollback_exc)[:150],flush=True)
        sys.exit(1)
print("=== SYNOLOGY SCHEDULE (READ ONLY) ===",flush=True)
cli=Path("/usr/syno/bin/synoschedtask")
if cli.is_file():
    result=subprocess.run([str(cli),"--get"],capture_output=True,text=True,
                          errors="replace",timeout=20)
    print("SYNOSCHEDTASK_GET exit="+str(result.returncode)+" lines="+str(len(result.stdout.splitlines())),flush=True)
    if result.returncode==0:
        lines=result.stdout.splitlines()
        markers=("telegram","scheduler","auto.deploy","auto_deploy","watchdog","rg_nas_","rg nas")
        relevant=[i for i,line in enumerate(lines) if any(m in line.lower() for m in markers)]
        print("SCHEDULE_MATCH_LINES",len(relevant),flush=True)
        for index in relevant[:20]:
            # Print only safe metadata, not task commands or credentials.
            s=lines[index]
            if any(k in s.lower() for k in ("name:","id:","state:","enabled:","enable:","type:")):
                safe="".join(ch for ch in s if ch.isalnum() or ch in " _-:.[]/")[:130]
                print("TASK_META",safe,flush=True)
            else:
                print("TASK_REFERENCE_PRESENT at line",index+1,flush=True)
    else:
        print("SCHEDULE_QUERY_ERROR",result.stderr.strip().replace("\n"," ")[:180],flush=True)
else:
    print("SYNOSCHEDTASK_NOT_FOUND",flush=True)
print("=== FINAL SYNTAX CHECK ===",flush=True)
for name in names:
    result=subprocess.run(["/bin/sh","-n",str(root/name)],capture_output=True,timeout=15)
    print("SCRIPT",name,"PASS" if result.returncode==0 else "ERROR",flush=True)
print("RG_TELEGRAM_CRLF_REPAIR: PASS - NO BOT OR SCHEDULER STARTED",flush=True)
PY
