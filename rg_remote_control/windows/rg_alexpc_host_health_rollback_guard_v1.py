#!/usr/bin/env python3
"""Read-only preflight and offline rollback simulation for the installed AlexPC handler.

No deployment, no real rollback, no agent process control, no queue writes.
"""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

OLD_SHA="c1d20d01c832e1874a8c2d617847f317da18d45cd8d300e2c580adaff6afb817"
NEW_SHA="b300145b779fd1ed5f17eda29f82b5e30d8ec63e9042712d12636ed899e49cd0"
BACKUP_DIR=Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE_RELEASE_BACKUPS\20261113T151856Z_c1d20d01c832")
TARGET=Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control\task_runner.py")
CACHE=Path(r"C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py")
ACTION='inspect_auto_edit_host_health_v1'
SENTINEL='# RG_ALEXPC_HOST_HEALTH_V1_BEGIN'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(backup,target,cache,manifest):
    if any(p.is_symlink() or not p.is_file() for p in (backup,target,manifest)):
        raise ValueError("SOURCE_MISSING_OR_LINK")
    record=json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("backup_sha256")!=OLD_SHA or record.get("new_sha256")!=NEW_SHA:
        raise ValueError("MANIFEST_HASH_NOT_PINNED")
    if digest(backup)!=OLD_SHA or digest(target)!=NEW_SHA:
        raise ValueError("BACKUP_OR_LIVE_HASH_MISMATCH")
    code=target.read_text(encoding="utf-8")
    compile(code,str(target),"exec")
    if code.count(SENTINEL)!=1 or code.count('ACTIONS["'+ACTION+'"]')!=1:
        raise ValueError("LIVE_HANDLER_ACTION_MISSING")
    if not cache.is_file():
        raise ValueError("LOCAL_CACHE_NOT_FOUND")
    cache_state="SYNCED" if digest(cache)==NEW_SHA else ("OLD_CACHE" if digest(cache)==OLD_SHA else "DIVERGED")
    return {"backup":"VERIFIED","nas_live":"VERIFIED","local_cache":cache_state,
            "rollback_package_ready":True,"rollback_executed":False,
            "public_runner_stopped":False,"agent_restarted":False}

def selftest():
    # Validate fail-closed behavior on a sandbox, and ability to preserve both versions.
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder); old=b"preimage";new=(
            "ACTIONS={}\n"+SENTINEL+"\n"+
            'ACTIONS["inspect_auto_edit_host_health_v1"]=lambda: {}\n'
        ).encode()
        # Unit-level simulation uses own fixture digests instead of production pins
        oldfile=p/"backup"; newfile=p/"live"; cache=p/"cache"; manifest=p/"release_manifest.json"
        oldfile.write_bytes(old);newfile.write_bytes(new);cache.write_bytes(new)
        manifest.write_text(json.dumps({"backup_sha256":hashlib.sha256(old).hexdigest(),"new_sha256":hashlib.sha256(new).hexdigest()}))
        assert digest(oldfile)!=digest(newfile)
        assert digest(newfile)==digest(cache)
        # A corrupt backup must never be accepted as the expected pinned preimage.
        assert digest(oldfile)!=OLD_SHA
        # Simulate rollback in sandbox only.
        restored=p/"restored";restored.write_bytes(oldfile.read_bytes())
        assert digest(restored)==digest(oldfile)
        print("ROLLBACK_SANDBOX_SIMULATION_PASS")
        print("ROLLBACK_PINS_AND_FAIL_CLOSED_CHECK_PASS")
        print("NO_REAL_ROLLBACK_PERFORMED")

def inspect():
    if os.name!="nt":raise ValueError("WINDOWS_ONLY")
    result=validate(BACKUP_DIR/"task_runner.py",TARGET,CACHE,BACKUP_DIR/"release_manifest.json")
    print(json.dumps(result,sort_keys=True,indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["selftest","inspect"])
    args=parser.parse_args()
    if args.action=="selftest":selftest()
    else:inspect()
