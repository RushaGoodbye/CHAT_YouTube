#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Targeted local recovery for 886_5 with conservative stale NAS request quarantine."""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import pathlib
import py_compile
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import urllib.request

APP=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNNER_URL="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/22c3672753524597b04637e315aa2ca89b8746fd/rg_remote_control/task_runner.py"
SHORT_VERSION="RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2"
NAS=pathlib.Path(r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC")

def emit(label, obj=None):
    print(label,flush=True)
    if obj is not None:
        print(json.dumps(obj,ensure_ascii=False,indent=2,default=str),flush=True)

def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))

def find_artifact(suffix):
    candidates=[APP/f"RG_EDITED_886_5_{suffix}",APP/"886"/f"RG_EDITED_886_5_{suffix}"]
    present=[p for p in candidates if p.is_file()]
    return max(present,key=lambda p:p.stat().st_mtime) if present else None

def check_processes():
    ps=r"""$p=Get-CimInstance Win32_Process | Where-Object {
  (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
  (($_.CommandLine -like '*rg_production_wrapper.py*') -or
   ($_.CommandLine -like '*rg_multi_dialogue.py*') -or
   ($_.CommandLine -like '*rg_auto_edit_one_button.py*'))
}
$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
    if p.returncode!=0:
        raise RuntimeError("Unable to verify production processes: "+p.stderr[-1200:])
    result=p.stdout.strip()
    if result not in ("", "null", "[]"):
        raise RuntimeError("Production already running; second launch prevented: "+result[:1400])

def prevent_queued_duplicate():
    for sub in ("requests","processing"):
        folder=NAS/"auto_edit"/sub
        if not folder.is_dir():
            continue
        pending=list(folder.glob("retry-8865-*.json"))
        if pending:
            raise RuntimeError("Existing queued 886 recovery request; duplicate prevented: "+str(pending[0]))

def quarantine_legacy_retry_request():
    """Archive only the one known V3 preparation request; never drop queued recovery jobs."""
    req_dir=NAS/"auto_edit"/"requests"
    proc_dir=NAS/"auto_edit"/"processing"
    pending_proc=list(proc_dir.glob("retry-8865-*.json")) if proc_dir.is_dir() else []
    if pending_proc:
        raise RuntimeError("886 retry is already PROCESSING on NAS: "+str(pending_proc[0]))
    if not req_dir.is_dir():
        raise RuntimeError("NAS request directory unavailable; cannot check for duplicates")
    queued=list(req_dir.glob("retry-8865-*.json"))
    if not queued:
        return
    # A live AlexPC agent could claim the request at any moment: never race it.
    ps=r"""$p=Get-CimInstance Win32_Process | Where-Object {
  (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
  ($_.CommandLine -like '*alexpc_agent.py*')
}
$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress
"""
    probe=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
        capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
    if probe.returncode!=0:
        raise RuntimeError("Cannot confirm agent is inactive; queue untouched: "+probe.stderr[-1200:])
    if probe.stdout.strip() not in ("","null","[]"):
        raise RuntimeError("AlexPC agent is running; request left in queue: "+probe.stdout.strip()[:900])
    agent_status=NAS/"status"/"alexpc_agent.json"
    if not agent_status.is_file():
        raise RuntimeError("Agent heartbeat absent; cannot safely quarantine NAS request")
    status=read_json(agent_status)
    updated=str(status.get("updated_at") or "")
    try:
        age=time.time()-datetime.datetime.fromisoformat(updated.replace("Z","+00:00")).timestamp()
    except (ValueError,TypeError,OverflowError):
        raise RuntimeError("Agent heartbeat timestamp invalid; queue untouched")
    if age<120:
        raise RuntimeError("Agent heartbeat too recent to archive request; queue untouched")
    # Whitelist the exact failed preparation action, not a runnable recovery action.
    if len(queued)!=1:
        raise RuntimeError("Multiple retry requests; manual inspection needed: "+repr([x.name for x in queued]))
    item=queued[0]
    if not item.name.startswith("retry-8865-apply_auto_edit_resume_protection_hotfix-"):
        raise RuntimeError("Unknown queued 886 request; NOT archived: "+item.name)
    payload=read_json(item)
    if (payload.get("action")!="apply_auto_edit_resume_protection_hotfix" or
            payload.get("request_id")!=item.stem or (payload.get("args") or {})!={}):
        raise RuntimeError("Queued request content differs from expected preparation request")
    if time.time()-item.stat().st_mtime<60:
        raise RuntimeError("Queued request is too recent to archive")
    archival=NAS/"auto_edit"/"quarantine"/"manual_recovery_886_5"
    archival.mkdir(parents=True,exist_ok=True)
    dest=archival/item.name
    if dest.exists():
        raise RuntimeError("Quarantine destination already exists; queue untouched")
    # Atomic move within NAS share, never delete. If an agent claimed it first, abort.
    os.replace(item,dest)
    emit("STALE V3 NAS REQUEST QUARANTINED",{"from":str(item),"to":str(dest),"agent_heartbeat_age_sec":round(age)})
    prevent_queued_duplicate()

def run_action(script,action,args):
    task={"target":"alexpc","contour":"auto_edit","action":action,"args":args}
    with tempfile.TemporaryDirectory(prefix="rg_8865_action_") as td:
        path=pathlib.Path(td)/"task.json"
        path.write_text(json.dumps(task,ensure_ascii=False),encoding="utf-8")
        p=subprocess.run([sys.executable,"-u","-X","utf8",str(script),str(path)],
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=360)
    if p.returncode!=0:
        raise RuntimeError(action+" failed: "+(p.stderr+"\n"+p.stdout)[-6500:])
    try:
        payload=json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(action+" returned invalid JSON: "+p.stdout[-3000:])
    if payload.get("action")!=action or not isinstance(payload.get("result"),dict):
        raise RuntimeError(action+" returned unexpected envelope: "+p.stdout[-3000:])
    return payload["result"]

def checkpoint_fingerprint(path):
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024*1024), b""):
            h.update(block)
    st=path.stat()
    return {"size":st.st_size,"mtime_ns":st.st_mtime_ns,"sha256":h.hexdigest()}

def collect_protected_checkpoints():
    """Find actual completed primary XML in either known output location. Never restore an unverified file."""
    protected=[]
    inventory={}
    for number in range(1,5):
        filename=f"RG_EDITED_886_{number}.xml"
        candidates=[APP/filename,APP/"886"/filename]
        rows=[]
        for path in candidates:
            item={"path":str(path),"exists":path.is_file()}
            if not path.is_file():
                rows.append(item)
                continue
            try:
                fp=checkpoint_fingerprint(path)
                item.update(fp)
                if fp["size"] < 1000:
                    raise RuntimeError("XML too small")
                tree=ET.parse(path)
                root=tree.getroot()
                if root.tag!="xmeml" or root.find("sequence") is None:
                    raise RuntimeError("not a Premiere sequence XML")
                if not root.findall(".//clipitem"):
                    raise RuntimeError("no clips")
                item["valid"]=True
                protected.append(path)
            except Exception as exc:
                item["valid"]=False
                item["error"]=str(exc)
            rows.append(item)
        inventory[str(number)]=rows
    missing=[n for n,rows in inventory.items() if not any(r.get("valid") for r in rows)]
    if missing:
        emit("=== 886 CHECKPOINT INVENTORY ===",inventory)
        raise RuntimeError("Missing valid saved XML for dialogue(s) "+",".join(missing)+
            ". No processing launched. Files may be outside active output directories.")
    return protected,inventory

def backup_protected_checkpoints(baseline):
    import shutil
    need=sum(info["size"] for info in baseline.values())
    if shutil.disk_usage(DATA).free < need+128*1024*1024:
        raise RuntimeError("Insufficient F: free space to back up protected XML")
    folder=DATA/"release_backups"/("PRE_886_5_RETRY_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True,exist_ok=False)
    for path,fp in baseline.items():
        sub="stream_folder" if path.parent==APP/"886" else "app_root"
        dst=folder/sub/path.name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dst)
        copied=checkpoint_fingerprint(dst)
        if copied["sha256"]!=fp["sha256"] or copied["size"]!=fp["size"]:
            raise RuntimeError("Protected checkpoint backup verification failed: "+str(path))
    return str(folder)

def check_qa(state,start_epoch,baseline):
    det=find_artifact("CIGARETTE_BLUR_DETECTIONS.json")
    qa=find_artifact("CIGARETTE_BLUR_QA.json")
    d=read_json(det) if det else {}
    q=read_json(qa) if qa else {}
    fresh_det=bool(det and det.stat().st_mtime>=start_epoch-2)
    fresh_qa=bool(qa and qa.stat().st_mtime>=start_epoch-2)
    stable=any(t.get("confirmation")=="SHORT_STABLE" for t in d.get("tracks",[]) if isinstance(t,dict))
    intervals=int(d.get("interval_count") or 0)
    overlays=int(q.get("overlay_count") or 0)
    protect_now={str(p):checkpoint_fingerprint(p) if p.is_file() else None for p in baseline}
    unchanged=all(protect_now.get(str(p))==old for p,old in baseline.items())
    current_cfg=read_json(APP/"rg_auto_edit_config.json").get("cigarette_blur") or {}
    safe=bool(current_cfg.get("mandatory") and current_cfg.get("fail_closed") and current_cfg.get("whole_frame_blur_forbidden") and
              current_cfg.get("version")==SHORT_VERSION)
    passed=bool(state.get("overall_ok") is True and fresh_det and fresh_qa and
                d.get("passed") is True and q.get("passed") is True and stable and intervals>0 and overlays>0 and unchanged and safe)
    return {
        "status":"PASS" if passed else "NEEDS_CHECK",
        "stream":"886","protected_dialogues":"1-4","retry_from_dialogue":5,
        "queue_overall_ok":state.get("overall_ok"),
        "queue_rows":state.get("rows"),
        "detection_file":str(det) if det else None,"qa_file":str(qa) if qa else None,
        "detection_fresh":fresh_det,"qa_fresh":fresh_qa,
        "confirmed_tracks":d.get("confirmed_track_count"),"short_stable_confirmed":stable,
        "intervals":intervals,"overlays":overlays,
        "detection_pass":d.get("passed"),"blur_qa_pass":q.get("passed"),
        "detection_failures":d.get("failures",[]),"blur_failures":q.get("failures",[]),
        "dialogs_1_to_4_unchanged":unchanged,"mandatory_blur_and_fail_closed":safe,
    }

def main():
    if os.name!="nt":
        raise RuntimeError("Windows-only AlexPC diagnostic")
    emit("=== 886_5 DIRECT RECOVERY PREFLIGHT ===")
    if not APP.is_dir() or not DATA.is_dir():
        raise RuntimeError("Auto Edit F: folders missing")
    cfg=read_json(APP/"rg_auto_edit_config.json").get("cigarette_blur") or {}
    if cfg.get("version")!=SHORT_VERSION or not (cfg.get("mandatory") and cfg.get("fail_closed") and cfg.get("whole_frame_blur_forbidden")):
        raise RuntimeError("Cigarette mandatory safety settings/version not correct; aborting")
    mod=APP/"rg_cigarette_blur.py"
    if not mod.is_file() or SHORT_VERSION not in mod.read_text(encoding="utf-8-sig"):
        raise RuntimeError("Installed SHORT_STABLE V2 module not found; aborting")
    check_processes()
    quarantine_legacy_retry_request()
    prevent_queued_duplicate()
    protected,inventory=collect_protected_checkpoints()
    baseline={p:checkpoint_fingerprint(p) for p in protected}
    emit("CHECKPOINTS 886_1..886_4 VERIFIED",{
        "paths":[str(p) for p in protected],
        "dialogues_covered":4,
    })
    with tempfile.TemporaryDirectory(prefix="rg_8865_retry_") as td:
        runner=pathlib.Path(td)/"task_runner.py"
        with urllib.request.urlopen(RUNNER_URL,timeout=40) as response:
            runner.write_bytes(response.read())
        py_compile.compile(str(runner),doraise=True)
        multi=APP/"rg_multi_dialogue.py"
        if not multi.is_file():
            raise RuntimeError("rg_multi_dialogue.py missing")
        if "RG_RESUME_PROTECT_PREFIX_V1" not in multi.read_text(encoding="utf-8-sig"):
            guard=run_action(runner,"apply_auto_edit_resume_protection_hotfix",{})
            if guard.get("status") not in ("APPLIED","ALREADY_APPLIED"):
                raise RuntimeError("Resume protection patch failed: "+repr(guard))
        code=multi.read_text(encoding="utf-8-sig")
        if "RG_RESUME_PROTECT_PREFIX_V1" not in code or "if i <= _rg_protect_prefix and not can_resume:" not in code:
            raise RuntimeError("Real protected resume guard missing")
        py_compile.compile(str(multi),doraise=True)
        check_processes()
        prevent_queued_duplicate()
        emit("RESUME PROTECTION: VERIFIED (886_1..886_4)")
        backup=backup_protected_checkpoints(baseline)
        emit("PROTECTED XML BACKUP: VERIFIED",{"folder":backup,"files":len(baseline)})
        start_epoch=time.time()
        launch=run_action(runner,"start_auto_edit_recovery_queue",{"streams":["886"],"protect_completed_prefix":4})
    if not launch.get("started") or launch.get("streams")!=["886"]:
        raise RuntimeError("Recovery did not confirm launch: "+repr(launch))
    status_path=pathlib.Path(str(launch.get("status_file") or ""))
    if not status_path.is_absolute():
        raise RuntimeError("Recovery returned invalid status file path")
    emit("=== RETRY 886_5 STARTED ===",{"pid":launch.get("pid"),"session_id":launch.get("session_id"),"status_file":str(status_path)})
    end=time.time()+12*3600
    last_stage=None
    last_update=time.time()
    state={}
    while time.time()<end:
        if status_path.is_file():
            try:state=read_json(status_path)
            except Exception:time.sleep(5);continue
            row=next((r for r in state.get("rows",[]) if str(r.get("stream"))=="886"),{})
            marker=(row.get("stage"),row.get("progress"),row.get("status"))
            if marker!=last_stage or time.time()-last_update>=300:
                emit("886 PROGRESS: "+str(row.get("status"))+" | "+str(row.get("stage"))+" | "+str(row.get("progress")))
                last_stage=marker
                last_update=time.time()
            if state.get("running") is False:
                break
        time.sleep(10)
    else:
        raise RuntimeError("Monitor timeout; inspect status file (no second job started): "+str(status_path))
    report=check_qa(state,start_epoch,baseline)
    emit("=== RETRY 886_5 FINAL RESULT ===",report)
    if report["status"]!="PASS":
        raise SystemExit(3)

if __name__=="__main__":
    try:main()
    except Exception as e:
        emit("=== RETRY 886_5 STOPPED SAFELY ===",{"error":repr(e),"message":str(e)})
        raise SystemExit(2)
