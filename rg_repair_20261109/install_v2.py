"""RG Repair V1 offline transactional installer and rollback.
NO process launching, no montage, no queue mutations, no runtime/network installs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime
FILES=("rg_release_health_gate.py",)
PATCH_VERSION="RG_REPAIR_20261109_V2_RELEASE"

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
INSTALLED=Path(os.environ.get("LOCALAPPDATA",r"C:\Users\fauto\AppData\Local"))/"Programs"/"RG Auto Edit"
QUEUE=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\studio_batch_queue.json")
DEFAULT_BACKUPS=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS")

def digest(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as stream:
        for b in iter(lambda:stream.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def process_blockers():
    if os.name!="nt":
        raise RuntimeError("Windows AlexPC required for installation")
    script=r'''$ErrorActionPreference="Stop";Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match "pythonw?\.exe|rg.auto.edit") -and
        ($_.CommandLine -match "rg_studio_main\.py|rg_studio_ui\.py|rg_multi_dialogue\.py|rg_auto_edit_one_button\.py|rg_production_wrapper\.py" -or
         $_.Name -match "RG.Auto.Edit")
    }|Select-Object ProcessId,Name,CommandLine|ConvertTo-Json -Compress'''
    cp=subprocess.run(["powershell.exe","-NoProfile","-Command",script],capture_output=True,text=True,
                      encoding="utf-8",errors="replace",timeout=25)
    if cp.returncode:raise RuntimeError("PROCESS_CHECK_FAILED: "+cp.stderr[-300:])
    try:
        rows=json.loads(cp.stdout) if cp.stdout.strip() else []
    except ValueError as e:raise RuntimeError("PROCESS_CHECK_UNREADABLE") from e
    return rows if isinstance(rows,list) else [rows]

def assert_idle():
    blockers=process_blockers()
    if blockers:raise RuntimeError("STUDIO_OR_VIDEO_WORKERS_RUNNING; close Studio normally before update. PIDs="+
                                  ",".join(str(x["ProcessId"]) for x in blockers))
    try:
        q=json.loads(QUEUE.read_text(encoding="utf-8-sig"))
    except (OSError,ValueError) as exc:
        raise RuntimeError("QUEUE_STATE_NOT_READABLE") from exc
    if q.get("running") or q.get("paused"):
        raise RuntimeError("QUEUE_STILL_RUNNING_OR_PAUSED")
    if any(str(row.get("status") or "").upper() in ("ПРАЦЮЄ","RUNNING") for row in q.get("rows",[]) if isinstance(row,dict)):
        raise RuntimeError("QUEUE_HAS_ACTIVE_ROW")

def apply(root,backup_root):
    assert_idle()
    root=Path(root)
    meta=json.loads((root/"RG_REPAIR_REPORT.json").read_text(encoding="utf-8"))
    if meta["version"]!=PATCH_VERSION:raise RuntimeError("PACKAGE_VERSION_MISMATCH")
    updated=[]
    for name in FILES:
        source=APP/name
        candidate=root/name
        if not source.is_file() or not candidate.is_file():
            raise RuntimeError("SOURCE_OR_CANDIDATE_MISSING: "+name)
        expected=meta["files"][name]
        if digest(source)!=expected["source_sha256"]:
            raise RuntimeError("ORIGINAL_CHANGED_SINCE_CANDIDATE_STAGING: "+name)
        if digest(candidate)!=expected["candidate_sha256"]:
            raise RuntimeError("CANDIDATE_TAMPER_OR_CORRUPTION: "+name)
        updated.append((source,candidate))
        target=INSTALLED/name
        if target.is_file():
            updated.append((target,candidate))
    backup=Path(backup_root)/(PATCH_VERSION+"_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    if backup.exists():raise RuntimeError("BACKUP_ID_ALREADY_EXISTS")
    backup.mkdir(parents=True)
    ledger=[]
    try:
        # Copy and verify EVERY original before any modification.
        for i,(target,candidate) in enumerate(updated):
            original=backup/("original_"+str(i)+".py")
            shutil.copy2(target,original)
            if digest(target)!=digest(original):raise RuntimeError("BACKUP_VERIFY_FAILED:"+str(target))
            ledger.append({"target":str(target),"backup":str(original),"sha256":digest(original),
                           "candidate_sha256":digest(candidate)})
        (backup/"ROLLBACK_LEDGER.json").write_text(json.dumps({
            "version":PATCH_VERSION,"status":"BACKUP_READY","items":ledger},indent=2),encoding="utf-8")
        # Second gate: Studio must still be closed immediately before write.
        assert_idle()
        for target,candidate in updated:
            tmp=target.with_name(target.name+".rg_repair_tmp")
            shutil.copy2(candidate,tmp)
            if digest(tmp)!=digest(candidate):raise RuntimeError("COPY_VALIDATION_FAILED:"+str(target))
            os.replace(tmp,target)
            if digest(target)!=digest(candidate):raise RuntimeError("INSTALLED_HASH_MISMATCH:"+str(target))
        (backup/"ROLLBACK_LEDGER.json").write_text(json.dumps({
            "version":PATCH_VERSION,"status":"INSTALLED","items":ledger},indent=2),encoding="utf-8")
        return {"status":"INSTALLED","backup":str(backup),"updated_files":[str(p) for p,_ in updated],
                "rollback_available":True}
    except Exception:
        for item in reversed(ledger):
            try:
                target=Path(item["target"])
                shutil.copy2(item["backup"],target)
            except OSError:pass
        raise

def rollback(backup_root):
    assert_idle()
    dirs=sorted((p for p in Path(backup_root).glob(PATCH_VERSION+"_*")
                 if (p/"ROLLBACK_LEDGER.json").is_file()),reverse=True)
    if not dirs:raise RuntimeError("NO_VERIFIED_BACKUP_AVAILABLE")
    folder=dirs[0]
    ledger=json.loads((folder/"ROLLBACK_LEDGER.json").read_text(encoding="utf-8"))
    if ledger.get("version")!=PATCH_VERSION:raise RuntimeError("BACKUP_VERSION_MISMATCH")
    items=ledger["items"]
    for item in items:
        source=Path(item["backup"])
        if not source.is_file() or digest(source)!=item["sha256"]:
            raise RuntimeError("BACKUP_CORRUPT: "+str(source))
    assert_idle()
    for item in reversed(items):
        target=Path(item["target"])
        tmp=target.with_name(target.name+".rg_rollback_tmp")
        shutil.copy2(item["backup"],tmp)
        os.replace(tmp,target)
        if digest(target)!=item["sha256"]:raise RuntimeError("ROLLBACK_HASH_MISMATCH:"+str(target))
    (folder/"ROLLBACK_LEDGER.json").write_text(json.dumps({
        "version":PATCH_VERSION,"status":"ROLLED_BACK","items":items},indent=2),encoding="utf-8")
    return {"status":"ROLLED_BACK","restored_files":[item["target"] for item in items]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--package-dir",type=Path,default=Path(__file__).resolve().parent/"candidate")
    p.add_argument("--backup-root",type=Path,default=DEFAULT_BACKUPS)
    action=p.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply",action="store_true")
    action.add_argument("--rollback-latest",action="store_true")
    args=p.parse_args()
    result=apply(args.package_dir,args.backup_root) if args.apply else rollback(args.backup_root)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
