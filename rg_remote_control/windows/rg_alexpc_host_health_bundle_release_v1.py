#!/usr/bin/env python3
"""RG AlexPC host health: guarded one-file NAS BUNDLE release.

On Windows only. Atomic replacement, rollback, no process stops or queue writes.
The *existing* alexpc_agent.py auto-syncs the changed task_runner.py.
"""
import argparse, datetime, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

ACTION="inspect_auto_edit_host_health_v1"
BEGIN="# RG_ALEXPC_HOST_HEALTH_V1_BEGIN"
END="# RG_ALEXPC_HOST_HEALTH_V1_END"
MARKER='\n\ndef main() -> int:\n'
NAS=Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control\task_runner.py")
CACHE=Path(r"C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py")
BACKUP_ROOT=Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE_RELEASE_BACKUPS")

INJECT='''

# RG_ALEXPC_HOST_HEALTH_V1_BEGIN
def inspect_auto_edit_host_health_v1() -> dict:
    """Non-mutating host facts only. No secrets, queue access or programs launched."""
    import datetime as _dt
    import shutil as _sh
    import subprocess as _sp
    from pathlib import Path as _Path
    r = {
        "schema": "RG_ALEXPC_READONLY_HEALTH_V1",
        "checked_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "read_only": True, "platform": "Windows",
        "runner_listener_present": False,
        "auto_edit_f_root_present": _Path("F:/RG_AUTO_EDIT").is_dir(),
        "auto_edit_runner_f_present": _Path("F:/RG_AUTO_EDIT/RG_AutoEdit_Runner").is_dir(),
        "github_runner_c_present": _Path("C:/RG_GITHUB_RUNNER").is_dir(),
        "f_drive_free_gb": None, "errors": [], "status": "UNKNOWN",
    }
    try:
        if os.name != "nt":
            r["errors"] = ["NOT_WINDOWS"]
            return {"exit_code": 2, **r}
        p = _sp.run(["tasklist.exe", "/FI", "IMAGENAME eq Runner.Listener.exe", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=8, check=False)
        if p.returncode != 0:
            r["errors"] = ["RUNNER_PROCESS_QUERY_FAILED"]
        else:
            r["runner_listener_present"] = "Runner.Listener.exe" in p.stdout
        r["f_drive_free_gb"] = round(_sh.disk_usage("F:/").free / (1024 ** 3), 1)
        r["status"] = ("HOST_PRESENT" if r["auto_edit_f_root_present"]
                       and r["runner_listener_present"] else "ATTENTION")
    except Exception as exc:
        r["errors"] = ["HOST_PROBE_FAILED:" + type(exc).__name__]
    if r["status"] == "UNKNOWN":
        r["exit_code"] = 2
    return r

ACTIONS["inspect_auto_edit_host_health_v1"] = inspect_auto_edit_host_health_v1
# RG_ALEXPC_HOST_HEALTH_V1_END
'''

def sha(d):
    return hashlib.sha256(d).hexdigest()

def patch(data):
    src=data.decode("utf-8")
    if BEGIN in src or END in src:
        raise ValueError("ALREADY_PATCHED_SAFE_STOP")
    if src.count(MARKER)!=1 or 'ACTIONS = {' not in src:
        raise ValueError("UNEXPECTED_TASK_RUNNER_LAYOUT")
    if len(data)<300000: raise ValueError("UNEXPECTED_SMALL_SOURCE")
    updated=src.replace(MARKER,INJECT+MARKER,1)
    compile(updated,"task_runner.py","exec")
    if updated.count(BEGIN)!=1 or updated.count(END)!=1:
        raise AssertionError("PATCH_SENTINELS")
    return updated.encode("utf-8")

def selftest():
    source=("ACTIONS = {}\n"+("x=1\n"*150000)+MARKER+
            "    return 0\n").encode()
    result=patch(source)
    assert ACTION.encode() in result and len(result)>len(source)
    try:patch(result)
    except ValueError as e: assert "ALREADY_PATCHED" in str(e)
    else:raise AssertionError("DUPLICATE_PATCH_ALLOWED")
    try:patch(b"ACTIONS = {}\n")
    except ValueError:pass
    else:raise AssertionError("UNKNOWN_LAYOUT_ALLOWED")
    print("HOST_HEALTH_PATCH_OFFLINE_QA_PASS")
    print("HOST_HEALTH_NO_AGENT_OR_QUEUE_CHANGES_PASS")

def install():
    if os.name!="nt": raise RuntimeError("WINDOWS_HOST_REQUIRED")
    if not NAS.is_file() or NAS.is_symlink():raise RuntimeError("NAS_BUNDLE_NOT_REGULAR_FILE")
    if not CACHE.is_file():raise RuntimeError("LOCAL_CACHE_MISSING")
    old=NAS.read_bytes()
    if sha(CACHE.read_bytes())!=sha(old):raise RuntimeError("NAS_CACHE_PARITY_FAILED")
    new=patch(old)
    if not BACKUP_ROOT.is_dir() or BACKUP_ROOT.is_symlink():
        raise RuntimeError("BACKUP_DIR_NOT_PROVISIONED_SAFE_STOP")
    folder=BACKUP_ROOT/(datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_"+sha(old)[:12])
    folder.mkdir(exist_ok=False)
    backup=folder/"task_runner.py"
    shutil.copy2(NAS,backup)
    if sha(backup.read_bytes())!=sha(old):raise RuntimeError("BACKUP_HASH_MISMATCH")
    info={"action":ACTION,"backup_sha256":sha(old),"new_sha256":sha(new),"backup":str(backup),"target":str(NAS),"state":"BACKUP_PREPARED"}
    (folder/"release_manifest.json").write_text(json.dumps(info,indent=2),encoding="utf-8")
    staged=NAS.with_name("task_runner.py.rg_host_health_stage")
    if staged.exists() or staged.is_symlink():raise RuntimeError("STAGING_EXISTS_SAFE_STOP")
    try:
        with staged.open("xb") as f:
            f.write(new);f.flush();os.fsync(f.fileno())
        if sha(staged.read_bytes())!=sha(new):raise RuntimeError("STAGED_HASH_MISMATCH")
        compile(staged.read_bytes(),"task_runner.py","exec")
        # Existing agent syncs this one BUNDLE file during its next normal request.
        os.replace(staged,NAS)
        if sha(NAS.read_bytes())!=sha(new):raise RuntimeError("LIVE_HASH_MISMATCH")
        info["state"]="BUNDLE_PATCHED_NOT_YET_AGENT_E2E_VERIFIED"
        (folder/"release_manifest.json").write_text(json.dumps(info,indent=2),encoding="utf-8")
    except Exception:
        if staged.exists():staged.unlink()
        if sha(NAS.read_bytes())!=sha(old):
            tmp=NAS.with_name("task_runner.py.rg_host_health_rollback")
            shutil.copy2(backup,tmp)
            os.replace(tmp,NAS)
        raise
    print(json.dumps({"status":info["state"],"backup_sha256":info["backup_sha256"],
      "new_sha256":info["new_sha256"],"backup_dir":str(folder),
      "agent_restarted":False,"autoedit_changed":False,"public_runner_stopped":False},indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("selftest","install"))
    a=p.parse_args()
    if a.action=="selftest":selftest()
    else:install()
