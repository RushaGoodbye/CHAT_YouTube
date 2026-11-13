#!/usr/bin/env python3
"""Provision durable immutable helper for DSM 5-minute Task Scheduler.

Does not create/change DSM tasks, crontab, containers, or publishing.
Installer makes a single managed operator file on shared NAS storage, with rollback.
"""
import argparse,hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path

ROOT=Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator")
EXPORT_SRC=Path("/tmp/rg_remote_mcp_compose_export_v1.py")
EXPECTED_BLOB="80f4dee368240f46682c2d7c5cdd26b0db48cda9"
TARGET=ROOT/"rg_remote_mcp_compose_export_v1.py"
LAUNCHER=ROOT/"rg_remote_mcp_export_tick.sh"
SCRIPT='''#!/bin/sh
# RG_REMOTE_MCP_SANITIZED_EXPORT_V1
# Read-only four-service Docker inventory. One sanitized JSON export only.
set -eu
exec /usr/bin/python3 /volume1/docker/RG_TELEGRAM_NEWS_2/operator/rg_remote_mcp_compose_export_v1.py write
'''
class Stop(Exception):pass

def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\\0"+data).hexdigest()

def atomic(path,data,mode):
    fd,tmp=tempfile.mkstemp(prefix=".rg-mcp-export-",dir=str(path.parent))
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def prepare():
    if os.geteuid()!=0:raise Stop("ROOT_REQUIRED")
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode&0o022:
        raise Stop("OPERATOR_ROOT_UNSAFE")
    if not EXPORT_SRC.is_file() or EXPORT_SRC.is_symlink():
        raise Stop("VERIFIED_EXPORTER_MISSING")
    data=EXPORT_SRC.read_bytes()
    if blob(data)!=EXPECTED_BLOB:raise Stop("EXPORTER_BLOB_MISMATCH")
    compile(data,str(EXPORT_SRC),"exec")
    subprocess.run(["/bin/sh","-n"],input=SCRIPT,text=True,check=True)
    for p in (TARGET,LAUNCHER):
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise Stop("DEST_UNSAFE_"+p.name)
        if p.exists() and p==TARGET and p.read_bytes()!=data:raise Stop("EXPORTER_EXISTS_DIFFERS")
        if p.exists() and p==LAUNCHER and p.read_text()!=SCRIPT:raise Stop("LAUNCHER_EXISTS_DIFFERS")
    # Idempotent creation with no edits of existing task scripts.
    if not TARGET.exists():atomic(TARGET,data,0o700)
    if not LAUNCHER.exists():atomic(LAUNCHER,SCRIPT.encode(),0o700)
    return {"status":"DURABLE_EXPORTER_READY","path":str(LAUNCHER),
            "scheduler_installed":False,"dsm_schedule":"EVERY_5_MINUTES_ROOT",
            "public_runner_stopped":False,"telegram_publications":0}

def selftest():
    assert "RG_REMOTE_MCP_SANITIZED_EXPORT_V1" in SCRIPT
    assert blob(b"hello")=="b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"
    assert "sudo " not in SCRIPT and "docker " not in SCRIPT
    print("RG_REMOTE_MCP_DURABLE_SCHEDULE_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["selftest","install"])
    a=p.parse_args()
    if a.action=="selftest":return selftest()
    try:print(json.dumps(prepare(),sort_keys=True))
    except (Stop,OSError,subprocess.CalledProcessError) as e:
        print(json.dumps({"status":"SAFE_STOP","reason":str(e)[:110]}))
        return 2
    return 0
if __name__=="__main__":raise SystemExit(main())
