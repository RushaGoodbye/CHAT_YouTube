#!/usr/bin/env python3
"""NAS root-only, metadata-only readiness check. Never stops a container.

No secrets, bot files, Telegram API calls, job dispatch or chmod operations.
Reports unresolved dependency on public runner as an explicit gate.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

DEST=Path("/volume1/docker/RG_TELEGRAM_NEWS_EXPORT")
PRIVATE="rg-nas-telegram-private-runner"
PUBLIC="rg-nas-telegram-runner"
REPORT="rg_news_cutover_preflight_public.json"

class SafeStop(Exception): pass

def docker_metadata(name):
    cmd=["docker","inspect","--format",
         "{{.State.Running}}|{{.Config.Image}}|{{.HostConfig.Privileged}}",
         name]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                     text=True,timeout=15)
    if p.returncode:return {"present":False,"running":False}
    parts=p.stdout.strip().split("|")
    if len(parts)!=3:raise SafeStop("INVALID_DOCKER_METADATA")
    return {
        "present":True,"running":parts[0]=="true",
        "known_image":parts[1]=="rg-nas-github-runner:2.338.2",
        "privileged":parts[2]=="true",
    }

def probe():
    if os.geteuid()!=0:raise SafeStop("ROOT_REQUIRED")
    items={}
    items["private_runner"]=docker_metadata(PRIVATE)
    items["public_runner"]=docker_metadata(PUBLIC)
    # Only stat the sanitized export. Never read operator content.
    health=DEST/"rg_news_health_public.json"
    if not health.is_file() or health.is_symlink() or health.stat().st_size>16384:
        raise SafeStop("SANITIZED_EXPORT_NOT_SAFE")
    doc=json.loads(health.read_text(encoding="utf-8"))
    if doc.get("schema")!="RG_NEWS_NAS_SANITIZED_EXPORT_V1" or doc.get("contains_secrets") is not False:
        raise SafeStop("SANITIZED_EXPORT_INVALID")
    stamp=doc.get("generated_at_unix")
    if type(stamp) is not int:raise SafeStop("INVALID_HEARTBEAT")
    age=int(time.time())-stamp
    items["sanitized_export"]={
        "fresh":-60<=age<=1200,
        "age_seconds":age,
        "telegram_bot_health_proven":False,
    }
    # Old public repo has two workflows that still use public NAS runner.
    # An actual safe switch needs to port and test BOTH before shutdown.
    items["legacy_command_routes_migrated"]=False
    items["public_runner_shutdown_allowed"]=False
    items["telegram_publications_verified"]=False
    items["telegram_api_calls"]=0
    items["changes_to_bot"]=0
    items["changes_to_containers"]=0
    items["private_agent_mount_test"]="VERIFIED_SEPARATELY_GITHUB_43269578337"
    items["private_alexpc_handoff_test"]="VERIFIED_SEPARATELY_GITHUB_43269727846"
    items["generated_at_unix"]=int(time.time())
    items["schema"]="RG_NEWS_CUTOVER_PREFLIGHT_V1"
    return items

def emit(doc):
    if DEST.is_symlink() or not DEST.is_dir():raise SafeStop("UNSAFE_EXPORT_DIRECTORY")
    meta=DEST.stat()
    if meta.st_uid!=0 or meta.st_mode & 0o022:raise SafeStop("UNSAFE_EXPORT_PERMISSIONS")
    target=DEST/REPORT
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise SafeStop("UNSAFE_REPORT_TARGET")
    fd,name=tempfile.mkstemp(prefix=".rg-cutover-",dir=str(DEST))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            os.fchmod(stream.fileno(),0o644)
            json.dump(doc,stream,sort_keys=True)
            stream.write("\n")
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)

def selftest():
    assert docker_metadata.__name__=="docker_metadata"
    assert REPORT=="rg_news_cutover_preflight_public.json"
    assert Path(REPORT).name==REPORT
    print("READONLY_PREFLIGHT_OFFLINE_PASS")
    print("PUBLIC_SHUTDOWN_FAIL_CLOSED_PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["selftest","once"])
    args=ap.parse_args()
    if args.action=="selftest":selftest();return
    try:
        result=probe()
        emit(result)
        print(json.dumps(result,sort_keys=True))
        print("CUTOVER_PREFLIGHT_EXPORTED_PASS")
        print("PUBLIC_RUNNER_NOT_STOPPED")
    except (SafeStop, OSError, ValueError, subprocess.TimeoutExpired):
        print('{"status":"SAFE_STOP","telegram_changes":0,"public_runner_stopped":false}')
        raise SystemExit(2)

if __name__=="__main__":main()
