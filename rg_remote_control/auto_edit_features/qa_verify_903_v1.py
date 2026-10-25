#!/usr/bin/env python3
"""Run QA ONLY on existing 903 Premiere XMLs. No re-edit/render/media writes."""
from __future__ import annotations
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
PYTHON=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
REPORT_NAMES=("RG_POSTRUN_QA.json","RG_XML_VERIFY_V51.json","RG_BOUNDARY_QA_V51.json")

def validate_manifest(obj):
    if (obj.get("stream")!="903" or obj.get("status")!="PARTIAL_REVIEW" or
        int(obj.get("dialogue_count") or 0)!=6):
        raise RuntimeError("Unexpected stream/manifest: refusing QA")
    found={int(x.get("index") or 0) for x in (obj.get("outputs") or []) if isinstance(x,dict)}
    held={int(x.get("index") or 0) for x in (obj.get("review_holds") or []) if isinstance(x,dict)}
    if found!={1,3,4,6} or held!={2,5}:
        raise RuntimeError(f"Unexpected 903 output/hold identities: {found}/{held}")
    for item in obj["outputs"]:
        n=Path(item.get("premiere_xml") or "").name
        if not re.fullmatch(r"RG_EDITED_903_[1346](?:_R[1-9][0-9]*)?\.xml",n):
            raise RuntimeError(f"Invalid primary XML name: {n}")
    return True

def summarize(report):
    checks={x.get("name"):x for x in (report.get("checks") or []) if isinstance(x,dict)}
    missing=str(checks.get("Повнота діалогів",{}).get("detail") or "")
    xmls=str(checks.get("XML створено",{}).get("detail") or "")
    results={
        "stream":report.get("stream"),
        "overall_passed":report.get("passed"),
        "missing":missing,
        "primary_xml_count":report.get("xml_count"),
        "xml_created":xmls,
        "xml_verify":checks.get("Перевірка XML",{}).get("ok"),
        "premiere":checks.get("Premiere сумісність",{}).get("ok"),
        "boundary":checks.get("Контроль меж",{}).get("ok"),
        "held_dialogues":[2,5],
    }
    results["valid_partial"]=(
        results["stream"]=="903"
        and report.get("passed") is False
        and "MISSING PRIMARY XML: 2,5" in missing
        and report.get("xml_count")==4
        and xmls.strip()=="4 XML"
        and results["xml_verify"] is True
        and results["premiere"] is True
        and results["boundary"] is True
    )
    return results

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true",help="Run real postrun QA; writes QA JSON only")
    args=p.parse_args()
    folder=APP/"903"
    mf=APP/"RG_EDITED_903_MULTI_DIALOGUE.json"
    if not (mf.is_file() and folder.is_dir() and PYTHON.is_file()):
        raise RuntimeError("Live 903 inputs/runtime missing")
    manifest=json.loads(mf.read_text(encoding="utf-8-sig"))
    validate_manifest(manifest)
    postrun=APP/"rg_studio_postrun.py"
    text=postrun.read_text(encoding="utf-8-sig")
    if "_status=='PARTIAL_REVIEW'" not in text:
        raise RuntimeError("QA partial manifest repair not applied")
    if not args.apply:
        print("RG_QA_903_VERIFY|"+json.dumps({"mode":"DRY_RUN","manifest":"PARTIAL_REVIEW","ready_xml":4,"held":[2,5],"media_writes":0,"xml_writes":0}))
        return 0
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup=DATA/"release_backups"/f"PRE_QA_903_ONLY_{stamp}"
    backup.mkdir(parents=True,exist_ok=False)
    existing={name:(folder/name).is_file() for name in REPORT_NAMES}
    for name in REPORT_NAMES:
        src=folder/name
        if src.is_file():shutil.copy2(src,backup/name)
    cmd=[str(PYTHON),"-u",str(postrun),"--stream","903","--folder",str(folder),"--outputs-json","[]"]
    env=os.environ.copy()
    env["RG_POSTRUN_QA_ONLY"]="1"
    result=subprocess.run(cmd,cwd=str(APP),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=240)
    try:
        if result.returncode not in (0,4):
            raise RuntimeError(f"QA process failed ({result.returncode}): "+result.stderr[-800:])
        qa=json.loads((folder/"RG_POSTRUN_QA.json").read_text(encoding="utf-8-sig"))
        outcome=summarize(qa)
        if not outcome["valid_partial"]:
            raise RuntimeError("QA regression mismatch: "+json.dumps(outcome,ensure_ascii=False))
    except Exception:
        for name in REPORT_NAMES:
            src=backup/name
            dst=folder/name
            if existing[name]:
                shutil.copy2(src,dst)
            else:
                dst.unlink(missing_ok=True)
        raise
    print("RG_QA_903_VERIFY|"+json.dumps({"mode":"QA_ONLY","verified":True,"outcome":outcome,
            "backup":str(backup),"media_writes":0,"xml_writes":0},ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
