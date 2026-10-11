#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final QA label consistency fix for a manifest-confirmed skipped screenshot.

No backend, no video/audio/XML writes; only QA collector text and QA-only rerun.
"""
import argparse,ast,datetime,json,os,shutil,subprocess,sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
P=APP/"rg_studio_postrun.py"
OLD='    expected_ids=sorted(primary_ids|uncensored_ids|manifest_expected|inventory_expected,key=lambda x:(x!="MAIN",int(x) if x.isdigit() else -1))'
NEW='    expected_ids=sorted((primary_ids|uncensored_ids|manifest_expected|inventory_expected)-_rg_verified_skips,key=lambda x:(x!="MAIN",int(x) if x.isdigit() else -1))'
TAG="# RG_POSTRUN_REAL_SIDECAR_AND_SKIP_QA_R1"
def state():
    m=json.loads((APP/"RG_EDITED_904_MULTI_DIALOGUE.json").read_text(encoding="utf-8-sig"))
    if m.get("status")!="DIALOGUES_COMPLETE" or m.get("dialogue_count")!=6 or len(m.get("outputs") or [])!=6:
        raise RuntimeError("904 manifest no longer complete")
    if not all((APP/"904"/("RG_EDITED_904_"+str(i)+".xml")).is_file() for i in (1,2,4,5,6,7)):
        raise RuntimeError("904 original XML missing")
    qa=json.loads((APP/"904"/"RG_POSTRUN_QA.json").read_text(encoding="utf-8-sig"))
    if not qa.get("passed"):raise RuntimeError("904 current QA is not successful")
def check_process():
    cp=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
        "Get-CimInstance Win32_Process | Where-Object { ($_.Name -in @('python.exe','pythonw.exe')) -and ($_.CommandLine -match 'rg_multi_dialogue[.]py|rg_auto_edit_one_button[.]py|rg_production_wrapper[.]py') } | Select-Object ProcessId | ConvertTo-Json -Compress"],
        capture_output=True,text=True,timeout=30)
    if cp.returncode!=0 or cp.stdout.strip() not in ("","null","[]"):
        raise RuntimeError("Backend busy or unavailable")
def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--shadow",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--verify",action="store_true")
    a=p.parse_args()
    if os.name!="nt":raise RuntimeError("Windows required")
    text=P.read_text(encoding="utf-8-sig")
    if text.count(TAG)!=1:raise RuntimeError("Original R1 patch missing")
    if a.verify:
        if text.count(NEW)!=1 or OLD in text:raise RuntimeError("Inconsistent expected IDs label")
        ast.parse(text)
        print("RG_904_POSTRUN_EXPECTED_IDS_R1B_VERIFY_PASS")
        return
    state();check_process()
    if text.count(OLD)!=1 or NEW in text:raise RuntimeError("Source changed or already patched")
    candidate=text.replace(OLD,NEW,1)
    ast.parse(candidate)
    if a.shadow:
        print("RG_904_POSTRUN_EXPECTED_IDS_R1B_SHADOW_PASS")
        return
    backup=DATA/"release_backups"/("PRE_904_QA_EXPECTED_IDS_R1B_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(P,backup/P.name)
    try:
        tmp=P.with_suffix(".r1b.tmp")
        tmp.write_text(candidate,encoding="utf-8")
        os.replace(tmp,P)
        if P.read_text(encoding="utf-8-sig").count(NEW)!=1:raise RuntimeError("After write mismatch")
    except BaseException:
        shutil.copy2(backup/P.name,P)
        raise
    print("RG_904_POSTRUN_EXPECTED_IDS_R1B_INSTALL_PASS",
          json.dumps({"backup":str(backup),"xml_modified":False,
              "source_audio_video_modified":False,"backend_started":False}))
if __name__=="__main__":
    main()
