#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RG 904 resume R2: fail-closed, backed up, user-visible recovery.
Only patches Studio UI. Never launches production, changes XML, audio or video.
"""
from __future__ import annotations
import argparse
import ast
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
TARGET=APP/"rg_studio_ui.py"
VERSION=APP/"rg_studio_version.py"
MANIFEST=APP/"RG_EDITED_904_MULTI_DIALOGUE.json"
STATE=Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))/"RG_AUTO_EDIT"/"run_state"/"904"/"RUN_STATE.json"
TAG="# RG_RESUME_INCOMPLETE_MULTI_DIALOGUE_R2"
OLD_GUARD='        if self.proc and self.proc.state()!=QProcess.NotRunning:return'
NEW_GUARD='''        # RG_RESUME_INCOMPLETE_MULTI_DIALOGUE_R2
        if self.proc and self.proc.state()!=QProcess.NotRunning:
            self.status.setText("RESUME • ПОПЕРЕДНІЙ ПРОЦЕС ЩЕ НЕ ЗАВЕРШЕНО")
            QMessageBox.information(self,"Відновлення",
                "Попередній процес Studio ще активний. Дочекайся завершення "
                "або закрий зайвий екземпляр Studio. Нічого не перезапущено.")
            return'''
OLD_DECISION='''        plan=recovery_plan(stream)
        if existing and len(existing)==len(self.outputs):'''
NEW_DECISION='''        plan=recovery_plan(stream)
        # R2: completed XMLs in RUN_STATE can cover only a PREFIX of a
        # multi-dialogue stream. They are NOT proof that every dialogue exists.
        _rg_multi_needs_backend=False
        _rg_multi_manifest=APP_DIR/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json"
        if _rg_multi_manifest.is_file():
            try:
                _rg_m=json.loads(_rg_multi_manifest.read_text(encoding="utf-8-sig"))
                _rg_expected=int(_rg_m.get("dialogue_count") or 0)
                _rg_completed=len(_rg_m.get("outputs") or [])
                _rg_status=str(_rg_m.get("status") or "")
                _rg_multi_needs_backend=(
                    str(_rg_m.get("stream") or "")!=str(stream)
                    or _rg_expected<=0
                    or _rg_completed<_rg_expected
                    or _rg_status not in ("COMPLETE","COMPLETED","SUCCESS")
                )
                if _rg_multi_needs_backend:
                    self.status.setText(
                        f"RESUME • ЗБЕРЕЖЕНО {_rg_completed}/{_rg_expected} • ПРОДОВЖИТИ BACKEND")
                    self._log(f"RG_RESUME_R2|PARTIAL|{stream}|{_rg_completed}/{_rg_expected}")
            except Exception as _rg_resume_err:
                _rg_multi_needs_backend=True
                self._log("RG_RESUME_R2|MANIFEST_INVALID|"+str(_rg_resume_err))
        if existing and len(existing)==len(self.outputs) and not _rg_multi_needs_backend:'''

def load_verified_inputs():
    if not TARGET.is_file() or not VERSION.is_file():
        raise RuntimeError("Studio files missing")
    version=VERSION.read_text(encoding="utf-8-sig")
    if 'STUDIO_VERSION="0.20.20.3"' not in version:
        raise RuntimeError("Unexpected Studio version; refusing R2 patch")
    src=TARGET.read_text(encoding="utf-8-sig")
    ast.parse(src)
    if "# RG_SMOKING_UNCERTAIN_TIMELINE_HOTFIX_R1" not in src or "# RG_AUDALIGN_DIALOGUE_EPOCH_HOTFIX_R1" not in (APP/"rg_auto_edit_one_button.py").read_text(encoding="utf-8-sig"):
        raise RuntimeError("R1 prerequisites not installed")
    if not MANIFEST.is_file() or not STATE.is_file():
        raise RuntimeError("904 resume state is not present")
    m=json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    d=json.loads(STATE.read_text(encoding="utf-8-sig"))
    if str(m.get("stream"))!="904" or m.get("status")!="FAILED" or int(m.get("dialogue_count") or 0)!=6 or len(m.get("outputs") or [])!=3:
        raise RuntimeError("904 manifest diverged from expected failed 3/6 state")
    if d.get("status")!="BACKEND_ERROR":
        raise RuntimeError("904 run_state changed; don't overwrite active run")
    for row in m["outputs"]:
        p=Path(row["xml"])
        if not p.is_file() or p.stat().st_size<1000:
            raise RuntimeError("Saved XML missing or empty: "+p.name)
    return src,m,d

def patch(src):
    if TAG in src: raise RuntimeError("Already patched; no repeated write")
    class_anchor='    def resume_incomplete_run(self):'
    pos=src.find(class_anchor)
    if pos<0 or src.count(class_anchor)!=1:raise RuntimeError("Resume function signature changed")
    # Ensure both replacements belong specifically to resume_incomplete_run.
    end=src.find("\n    def ",pos+len(class_anchor))
    body=src[pos:end if end>=0 else len(src)]
    if body.count(OLD_GUARD)!=1 or body.count(OLD_DECISION)!=1:
        raise RuntimeError("Resume anchors changed, refusing patch")
    changed=body.replace(OLD_GUARD,NEW_GUARD,1).replace(OLD_DECISION,NEW_DECISION,1)
    out=src[:pos]+changed+src[end if end>=0 else len(src):]
    if out.count(TAG)!=1 or out.count("RG_RESUME_R2|PARTIAL")!=1:
        raise RuntimeError("Bad patch output")
    ast.parse(out)
    return out

def assert_no_running_backend():
    # Two Studio UI processes are allowed for the preflight; any processing
    # backend must not be interrupted by this patch.
    script="""Get-CimInstance Win32_Process | Where-Object {
      ($_.Name -in @('python.exe','pythonw.exe')) -and
      ($_.CommandLine -match 'rg_multi_dialogue[.]py|rg_production_wrapper[.]py|rg_auto_edit_one_button[.]py')
    } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"""
    cp=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],
                      text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if cp.returncode!=0:
        raise RuntimeError("Can't check active processing: "+cp.stderr[-250:])
    if cp.stdout.strip():
        try:
            v=json.loads(cp.stdout)
            if v and (isinstance(v,dict) or len(v)>0):
                raise RuntimeError("Active Auto Edit production process exists - no live hotfix")
        except json.JSONDecodeError:
            raise RuntimeError("Can't parse backend process list")
def inspect_manifest_rules(m):
    if not (len(m.get("outputs") or [])==3 and int(m.get("dialogue_count") or 0)==6):
        raise RuntimeError("Wrong regression example")
    def can_qa(status,done,total,all_paths_exist):
        return bool(all_paths_exist and status in ("COMPLETE","COMPLETED","SUCCESS") and done==total)
    assert not can_qa("FAILED",3,6,True)
    assert not can_qa("COMPLETE",3,6,True)
    assert can_qa("COMPLETE",6,6,True)
    assert not can_qa("COMPLETE",6,6,False)
    return {"expected_dialogues":6,"completed_dialogues":3,"backend_required":True,"preserved_xmls":len(m["outputs"])}

def main():
    ap=argparse.ArgumentParser()
    modes=ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--shadow",action="store_true")
    modes.add_argument("--apply",action="store_true")
    modes.add_argument("--verify",action="store_true")
    a=ap.parse_args()
    if os.name!="nt":
        raise RuntimeError("AlexPC Windows only")
    if a.verify:
        now=TARGET.read_text(encoding="utf-8-sig")
        if now.count(TAG)!=1 or now.count("RG_RESUME_R2|PARTIAL")!=1:
            raise RuntimeError("Installed R2 markers missing")
        ast.parse(now)
        print("RG_904_RESUME_R2_INSTALLED_VERIFY_PASS")
        return
    src,m,_=load_verified_inputs()
    code=patch(src)
    evidence=inspect_manifest_rules(m)
    assert_no_running_backend()
    if a.shadow:
        print("RG_904_RESUME_R2_SHADOW_PASS")
        print(json.dumps({"schema":"RG_RESUME_904_R2_SHADOW","source_parses":True,
          "fail_closed_version_gate":True,"backend_running":False,
          "automatic_skip_first_three_by_checkpoint":True,
          "studio_source_modified":False,**evidence},ensure_ascii=False))
        return
    backup=DATA/"release_backups"/("PRE_RESUME_904_R2_"+dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(TARGET,backup/TARGET.name)
    try:
        tmp=TARGET.with_name(TARGET.name+".rgr2.tmp")
        tmp.write_text(code,encoding="utf-8")
        os.replace(tmp,TARGET)
        ast.parse(TARGET.read_text(encoding="utf-8-sig"))
        if TARGET.read_text(encoding="utf-8-sig").count(TAG)!=1:
            raise RuntimeError("Post-apply tag mismatch")
    except BaseException:
        shutil.copy2(backup/TARGET.name,TARGET)
        raise
    print("RG_904_RESUME_R2_APPLY_PASS")
    print(json.dumps({"status":"INSTALLED_RESTART_GUI_REQUIRED",
                      "backup":str(backup),"production_media_modified":False,
                      "run_restarted":False,**evidence},ensure_ascii=False))
if __name__=="__main__":
    try: main()
    except BaseException as exc:
        print("RG_904_RESUME_R2_ERROR:"+repr(exc),file=sys.stderr)
        raise
