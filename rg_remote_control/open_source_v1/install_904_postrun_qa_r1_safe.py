#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""904 final QA R1: strict path-aware cigarette reports and documented skipped shots.

Production backend is NOT launched. Installed postrun changes only after shadow
and backup. The existing XML, source video/audio and 886_5 quarantine stay
untouched. No blanket QA override or false-pass allowed.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
TARGET=APP/"rg_studio_postrun.py"
STREAM="904"
TAG="# RG_POSTRUN_REAL_SIDECAR_AND_SKIP_QA_R1"
HELPER=String.raw if False else ""  # Not used; static code inserted below.

INJECT= '''# RG_POSTRUN_REAL_SIDECAR_AND_SKIP_QA_R1
def _rg_verified_root_xml_for_qa(x):
    """Use APP-root sidecar only with a byte-identical APP-root XML."""
    import hashlib
    x=Path(x)
    side=x.with_name(x.stem+"_CIGARETTE_BLUR_QA.json")
    if side.is_file():
        return x
    app=Path(__file__).resolve().parent
    candidate=app/x.name
    q=app/(x.stem+"_CIGARETTE_BLUR_QA.json")
    if not x.is_file() or not candidate.is_file() or not q.is_file():
        return x
    def digest(p):
        h=hashlib.sha256()
        with p.open("rb") as f:
            for b in iter(lambda:f.read(1048576),b""):
                h.update(b)
        return h.hexdigest()
    return candidate if digest(x)==digest(candidate) else x


def _rg_documented_skipped_ids(root,stream,primary_ids):
    """Only explicitly rejected frames of a completed, verified manifest."""
    import re
    p=_multi_dialogue_manifest(root,stream)
    if not p or not Path(p).is_file():return set()
    m=json.loads(Path(p).read_text(encoding="utf-8-sig"))
    rows=m.get("outputs") or []
    if (str(m.get("stream"))!=str(stream)
        or str(m.get("status"))!="DIALOGUES_COMPLETE"
        or int(m.get("dialogue_count") or 0)!=len(rows)
        or not rows):return set()
    generated=set()
    seen_indexes=set()
    for row in rows:
        if not isinstance(row,dict):return set()
        index=int(row.get("index") or 0)
        if index<1 or index in seen_indexes:return set()
        seen_indexes.add(index)
        name=Path(row.get("xml") or "").name
        rx=re.fullmatch("RG_EDITED_"+re.escape(str(stream))+r"_(\\d+)\\.xml",name,re.I)
        if not rx:return set()
        generated.add(rx.group(1))
        if not (root/name).is_file():return set()
    if generated!=set(primary_ids):return set()
    result=set()
    for item in m.get("skipped_screenshots") or []:
        if (not isinstance(item,dict)
            or item.get("accepted") is not False
            or item.get("reason")!="NO_GUEST_IN_RIGHT_WINDOW"):
            continue
        name=Path(str(item.get("screenshot") or "")).name
        hit=re.fullmatch(re.escape(str(stream))+r"-(\\d+)\\.(?:jpg|jpeg|png)",name,re.I)
        if not hit:continue
        i=hit.group(1)
        if i not in generated:result.add(i)
    return result


'''

ANCHOR='def main():\n'
OLD_EXPECT='    all_expected=uncensored_ids|manifest_expected|inventory_expected\n'
NEW_EXPECT='''    # RG QA skips only manifest-proven rejected screenshots, not missing dialogues.
    _rg_verified_skips=_rg_documented_skipped_ids(root,a.stream,primary_ids)
    all_expected=(uncensored_ids|manifest_expected|inventory_expected)-_rg_verified_skips
    if _rg_verified_skips:
        add("Скріншоти без гостя",True,
            "Документовано пропущено: "+",".join(sorted(_rg_verified_skips)),False)
'''
OLD_SIDECAR='        _q=_x.with_name(_x.stem+"_CIGARETTE_BLUR_QA.json")\n'
NEW_SIDECAR='        _q=_rg_verified_root_xml_for_qa(_x).with_name(_x.stem+"_CIGARETTE_BLUR_QA.json")\n'
OLD_OP='    _rg_cig=summarize_cigarette_qas(outs)\n'
NEW_OP='    _rg_cig=summarize_cigarette_qas([_rg_verified_root_xml_for_qa(x) for x in outs])\n'
OLD_CLEAN='    try:cleanup_operational_artifacts(retain_days=7)\n'
NEW_CLEAN='    if os.environ.get("RG_POSTRUN_QA_ONLY")!="1":\n        try:cleanup_operational_artifacts(retain_days=7)\n        except Exception:pass\n'
# The next legacy except must be removed when replacing OLD_CLEAN.
OLD_CLEAN_FULL=OLD_CLEAN+'    except Exception:pass\n'

def hash_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def six_xmls():
    return [APP/STREAM/f"RG_EDITED_{STREAM}_{i}.xml" for i in (1,2,4,5,6,7)]

def check_truth():
    version=(APP/"rg_studio_version.py").read_text(encoding="utf-8-sig")
    if 'STUDIO_VERSION="0.20.20.3"' not in version:
        raise RuntimeError("Unexpected installed Studio version")
    man=json.loads((APP/f"RG_EDITED_{STREAM}_MULTI_DIALOGUE.json").read_text(encoding="utf-8-sig"))
    if not (man.get("status")=="DIALOGUES_COMPLETE" and man.get("dialogue_count")==6
            and len(man.get("outputs") or [])==6):
        raise RuntimeError("904 not complete; refusal")
    skipped=man.get("skipped_screenshots") or []
    if not any(x.get("accepted") is False and x.get("screenshot")=="904-3.jpg"
               and x.get("reason")=="NO_GUEST_IN_RIGHT_WINDOW" for x in skipped):
        raise RuntimeError("Unexpected screenshot skip")
    evidence=[]
    for x in six_xmls():
        if not x.is_file():raise RuntimeError("Missing original XML "+x.name)
        rootxml=APP/x.name
        qa=APP/(x.stem+"_CIGARETTE_BLUR_QA.json")
        if not rootxml.is_file() or not qa.is_file() or hash_file(x)!=hash_file(rootxml):
            raise RuntimeError("Root XML and sidecar not safely matched "+x.name)
        d=json.loads(qa.read_text(encoding="utf-8-sig"))
        cov=d.get("coverage_qa") or {}
        if not d.get("passed") or cov.get("missing_frames",999)!=0 or float(cov.get("coverage_ratio") or 0)<.999999:
            raise RuntimeError("Real cigarette QA failed "+qa.name)
        evidence.append({"xml":x.name,"qa":"PASS","coverage":cov.get("coverage_ratio"),"overlays":d.get("overlay_count")})
    return evidence

def patch(text):
    if TAG in text:raise RuntimeError("Already applied; no repeated patch")
    if text.count(ANCHOR)!=1:raise RuntimeError("Missing module main")
    for old in (OLD_EXPECT,OLD_SIDECAR,OLD_OP,OLD_CLEAN_FULL):
        if text.count(old)!=1:raise RuntimeError("Postrun source anchors changed")
    result=text.replace(ANCHOR,INJECT+ANCHOR,1)
    for old,new in ((OLD_EXPECT,NEW_EXPECT),(OLD_SIDECAR,NEW_SIDECAR),
                    (OLD_OP,NEW_OP),(OLD_CLEAN_FULL,NEW_CLEAN)):
        result=result.replace(old,new,1)
    ast.parse(result)
    if result.count(TAG)!=1:raise RuntimeError("Wrong patch marker")
    return result

def active_backend():
    cmd="Get-CimInstance Win32_Process | Where-Object { ($_.Name -in @('python.exe','pythonw.exe')) -and ($_.CommandLine -match 'rg_multi_dialogue[.]py|rg_auto_edit_one_button[.]py|rg_production_wrapper[.]py') } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    proc=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",cmd],
        capture_output=True,text=True,timeout=30)
    if proc.returncode:raise RuntimeError("Unable to confirm idle backend")
    val=proc.stdout.strip()
    if val and val not in ("null","[]"):raise RuntimeError("Backend running; do not patch or QA rerun")

def verify():
    current=TARGET.read_text(encoding="utf-8-sig")
    if current.count(TAG)!=1:raise RuntimeError("QA patch not present")
    ast.parse(current)
    assert len(check_truth())==6
    import importlib.util
    spec=importlib.util.spec_from_file_location("rg_studio_postrun_r1_probe",TARGET)
    # No module execution here - running would load imports but not main.
    # Evaluate the pure new helper on strict ground-truth 904 data via exec.
    tree=ast.parse(current)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef)
            and n.name in ("_rg_verified_root_xml_for_qa","_rg_documented_skipped_ids","_multi_dialogue_manifest")]
    subset=ast.Module(body=functions,type_ignores=[])
    ns={"Path":Path,"json":json,"__file__":str(TARGET)}
    exec(compile(subset,str(TARGET),"exec"),ns,ns)
    ids={"1","2","4","5","6","7"}
    skipped=ns["_rg_documented_skipped_ids"](APP/STREAM,STREAM,ids)
    if skipped!={"3"}:raise RuntimeError("Unexpected skipped set "+repr(skipped))
    for p in six_xmls():
        actual=ns["_rg_verified_root_xml_for_qa"](p)
        if actual!=APP/p.name:raise RuntimeError("Root sidecar proof failed")
    return {"skipped":{"3":"NO_GUEST_IN_RIGHT_WINDOW"},"resolved_qas":6}

def main():
    parser=argparse.ArgumentParser()
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--shadow",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--verify",action="store_true")
    g.add_argument("--rerun-qa",action="store_true")
    args=parser.parse_args()
    if os.name!="nt":raise RuntimeError("Windows AlexPC only")
    if args.verify:
        print("RG_904_POSTRUN_QA_R1_INSTALLED_PASS",json.dumps(verify(),ensure_ascii=False))
        return
    if args.rerun_qa:
        v=verify()
        active_backend()
        # Preserve old report if the QA subprocess does not prove real PASS.
        report=APP/STREAM/"RG_POSTRUN_QA.json"
        bak=DATA/"release_backups"/"904_POSTRUN_QA_R1_original.json"
        bak.parent.mkdir(parents=True,exist_ok=True)
        if report.is_file() and not bak.is_file():shutil.copy2(report,bak)
        from_rg=Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))/"RG_AUTO_EDIT"/"run_state"/STREAM/"RUN_STATE.json"
        state=json.loads(from_rg.read_text(encoding="utf-8-sig"))
        pm=state.get("preflight_manifest")
        if not pm or not Path(pm).is_file():raise RuntimeError("Missing original preflight manifest")
        outs=[str(x) for x in six_xmls()]
        before={x.name:hash_file(x) for x in six_xmls()}
        args_run=[sys.executable,"-X","utf8",str(TARGET),"--stream",STREAM,
             "--folder",str(APP/STREAM),"--outputs-json",json.dumps(outs),
             "--preflight-manifest",str(pm),"--started-at","0"]
        env=os.environ.copy();env["RG_POSTRUN_QA_ONLY"]="1"
        result=subprocess.run(args_run,cwd=str(APP),env=env,stdout=subprocess.PIPE,
             stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",timeout=180)
        after=json.loads(report.read_text(encoding="utf-8-sig")) if report.is_file() else {}
        checks=[{"name":c.get("name"),"ok":c.get("ok"),"detail":str(c.get("detail") or "")[:150]}
            for c in after.get("checks") or []]
        if any(hash_file(x)!=before[x.name] for x in six_xmls()):
            raise RuntimeError("Original XML changed during postrun QA")
        if result.returncode or not after.get("passed") or any(not x["ok"] for x in checks):
            print("RG_904_POSTRUN_QA_R1_RECHECK_FAILED",
                  json.dumps({"return_code":result.returncode,"checks":checks,
                              "stderr_tail":result.stderr[-1400:]},ensure_ascii=False))
            raise RuntimeError("Postrun QA did not pass, no false PASS")
        print("RG_904_POSTRUN_QA_R1_RECHECK_PASS",
              json.dumps({"xml_count":after.get("xml_count"),"passed":after.get("passed"),
                     "checks":checks,"original_xml_unchanged":True,
                     "source_audio_video_unchanged":True,"no_production_backend_started":True},ensure_ascii=False))
        return
    evidence=check_truth()
    current=TARGET.read_text(encoding="utf-8-sig")
    fixed=patch(current)
    active_backend()
    if args.shadow:
        print("RG_904_POSTRUN_QA_R1_SHADOW_PASS",
            json.dumps({"verified_real_qas":evidence,
             "missing_904_3_documented":True,"installed_code_changed":False},ensure_ascii=False))
        return
    backup=DATA/"release_backups"/("PRE_904_POSTRUN_QA_R1_"+time.strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(TARGET,backup/TARGET.name)
    try:
        temp=TARGET.with_suffix(".rg904tmp")
        temp.write_text(fixed,encoding="utf-8")
        os.replace(temp,TARGET)
        verify()
    except BaseException:
        shutil.copy2(backup/TARGET.name,TARGET)
        raise
    print("RG_904_POSTRUN_QA_R1_INSTALL_PASS",
          json.dumps({"backup":str(backup),"source_xml_not_modified":True,
                      "video_audio_not_modified":True,"installed":True},ensure_ascii=False))
if __name__=="__main__":
    try:main()
    except BaseException as ex:
        print("RG_904_POSTRUN_QA_R1_ERROR:"+repr(ex),file=sys.stderr)
        raise
