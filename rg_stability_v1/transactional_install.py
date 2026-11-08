"""Transactional installer for RG Stability V1, user-initiated only.

Requires Studio to be fully closed and no montage processes active.
The workflow must check running Windows processes immediately before calling this.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from .stage_studio_patch import create_candidate
except ImportError:
    from stage_studio_patch import create_candidate

RUNTIME_MODULES = (
    "__init__.py",
    "rg_studio_adapter.py",
    "rg_compact_progress.py",
    "rg_stability_readonly.py",
    "rg_watchdog.py",
    "rg_resources.py",
    "rg_errors.py",
    "rg_xml_structural.py",
    "rg_output_audit.py",
    "rg_nightly_report.py",
)

def sha256(path:Path)->str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_queue(path:Path)->dict:
    try:
        o=json.loads(path.read_text(encoding="utf-8-sig"))
        return o if isinstance(o,dict) else {}
    except (FileNotFoundError,ValueError,OSError):
        return {}

def safety_check(*, source:Path, installed:Path, queue_path:Path, active_workers:int,
                 studio_running:bool)->dict:
    problems=[]
    if active_workers:problems.append("ACTIVE_VIDEO_WORKERS")
    if studio_running:problems.append("STUDIO_PROCESS_STILL_RUNNING")
    q=read_queue(queue_path)
    if not q:problems.append("QUEUE_STATE_UNREADABLE")
    elif q.get("running") or q.get("paused"):problems.append("QUEUE_STILL_RUNNING_OR_PAUSED")
    rows=q.get("rows",[])
    # A running result saved in the UI file is a hard blocker even if the process disappeared.
    if any(isinstance(x,dict) and str(x.get("status") or "").upper() in
           {"ПРАЦЮЄ","RUNNING"} for x in rows):
        problems.append("ACTIVE_QUEUE_ROW")
    if any(isinstance(x,dict) and str(x.get("status") or "").upper() in
           {"ОЧІКУЄ","ПРАЦЮЄ","RUNNING","WAITING","PENDING"} for x in rows):
        problems.append("UNFINISHED_QUEUE_ITEMS")
    if not source.is_file() or not installed.is_file():
        problems.append("STUDIO_SOURCE_MISSING")
    elif sha256(source)!=sha256(installed):
        problems.append("SOURCE_INSTALLED_DIVERGED")
    return {"safe":not problems,"problems":problems,
            "queue_count":len(q.get("queue") or []),
            "source":str(source),"installed":str(installed)}


def install(*, repo_package:Path, source:Path, installed:Path, queue_path:Path,
            active_workers:int, studio_running:bool, backup_root:Path,
            apply:bool=False)->dict:
    gate=safety_check(source=source,installed=installed,queue_path=queue_path,
                      active_workers=active_workers,studio_running=studio_running)
    if not gate["safe"] or not apply:
        return {"status":"BLOCKED" if not gate["safe"] else "CHECK_ONLY",
                "gate":gate,"installed":False}
    repo_package=Path(repo_package)
    for name in RUNTIME_MODULES:
        if not (repo_package/name).is_file():
            raise FileNotFoundError("Missing runtime module: "+name)
    source_root=Path(source).parent
    installed_root=Path(installed).parent
    targets=[(source_root,Path(source)),(installed_root,Path(installed))]
    with tempfile.TemporaryDirectory(prefix="rg_stability_v1_stage_") as temp:
        staged=Path(temp)
        candidate=create_candidate(source,staged)
        candidate_ui=staged/Path(source).name
        # Ensure the actual checked-in adapter compiles before changing any files.
        import ast
        for name in RUNTIME_MODULES:
            ast.parse((repo_package/name).read_text(encoding="utf-8"),filename=name)
        ast.parse(candidate_ui.read_text(encoding="utf-8"))
        backup=Path(backup_root)/("RG_STABILITY_V1_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        rollback=[]
        try:
            # Record every target including any existing Stability V1 package.
            for root,ui in targets:
                tag="SOURCE" if root==source_root else "INSTALLED"
                original=backup/tag
                original.mkdir()
                shutil.copy2(ui,original/ui.name)
                rollback.append(("file",ui,original/ui.name))
                package=root/"rg_stability_v1"
                oldpkg=original/"rg_stability_v1"
                if package.exists():
                    shutil.copytree(package,oldpkg)
                    rollback.append(("dir",package,oldpkg))
                else:
                    rollback.append(("newdir",package,None))
            # Stage package and UI atomically per file, with rollback for partial writes.
            for root,ui in targets:
                package=root/"rg_stability_v1"
                package.mkdir(parents=True,exist_ok=True)
                for name in RUNTIME_MODULES:
                    target=package/name
                    tmp=target.with_suffix(target.suffix+".rgv1tmp")
                    shutil.copy2(repo_package/name,tmp)
                    os.replace(tmp,target)
                ui_tmp=ui.with_suffix(".rgv1tmp")
                shutil.copy2(candidate_ui,ui_tmp)
                os.replace(ui_tmp,ui)
            if sha256(source)!=sha256(installed):
                raise RuntimeError("Post-install sources differ")
            for root,ui in targets:
                if "RG_STABILITY_V1_STAGED_ATTACH" not in ui.read_text(encoding="utf-8"):
                    raise RuntimeError("UI marker missing "+str(ui))
                for name in RUNTIME_MODULES:
                    if sha256(root/"rg_stability_v1"/name)!=sha256(repo_package/name):
                        raise RuntimeError("Module verification failed: "+name)
            result={"status":"INSTALLED","backup":str(backup),"installed":True,
                    "gate":gate,"rollback_available":True,
                    "ui_hash":sha256(source),"candidate":candidate}
            (backup/"INSTALL_REPORT.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
            return result
        except Exception:
            for kind,target,old in reversed(rollback):
                try:
                    if kind=="file":shutil.copy2(old,target)
                    elif kind=="newdir" and target.exists():shutil.rmtree(target)
                    elif kind=="dir":
                        if target.exists():shutil.rmtree(target)
                        shutil.copytree(old,target)
                except Exception:pass
            raise


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo-package",type=Path,required=True)
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--installed",type=Path,required=True)
    ap.add_argument("--queue",type=Path,required=True)
    ap.add_argument("--workers",type=int,required=True)
    ap.add_argument("--studio-running",action="store_true")
    ap.add_argument("--backup-root",type=Path,required=True)
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    result=install(repo_package=args.repo_package,source=args.source,
                   installed=args.installed,queue_path=args.queue,
                   active_workers=args.workers,studio_running=args.studio_running,
                   backup_root=args.backup_root,apply=args.apply)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if result["status"]=="BLOCKED":raise SystemExit(3)
