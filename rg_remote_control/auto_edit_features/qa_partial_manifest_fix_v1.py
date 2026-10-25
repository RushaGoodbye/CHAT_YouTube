#!/usr/bin/env python3
"""Repair live RG Auto Edit postrun PARTIAL_REVIEW reporting without editing media.

Default: dry-run, parse and unit-check patched module.
--apply: backed-up and atomic replacement of rg_studio_postrun.py only.
"""
from __future__ import annotations
import argparse
import ast
import datetime
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
FILENAME = "rg_studio_postrun.py"

OLD = """                if (str(manifest.get('stream'))==str(stream)
                    and str(manifest.get('status'))=='DIALOGUES_COMPLETE'
                    and int(manifest.get('dialogue_count') or 0)==len(rows)
                    and rows):"""

NEW = """                _status=str(manifest.get('status') or '')
                _expected=int(manifest.get('dialogue_count') or 0)
                _holds=manifest.get('review_holds') or []
                _complete=(_status=='DIALOGUES_COMPLETE' and _expected==len(rows))
                _partial=(_status=='PARTIAL_REVIEW'
                          and isinstance(_holds,list) and _expected>len(rows)>0
                          and len(rows)+len(_holds)==_expected
                          and all(isinstance(h,dict) and str(h.get('index') or '').isdigit()
                                  for h in _holds))
                if (str(manifest.get('stream'))==str(stream)
                    and isinstance(rows,list) and rows
                    and (_complete or _partial)):"""

OLD2 = """                    if good:
                        return authoritative"""
NEW2 = """                    if good and _partial:
                        held={str(h['index']) for h in _holds}
                        if len(held)!=len(_holds) or held & ids:
                            good=False
                    if good:
                        return authoritative"""

def patch_source(source: str) -> tuple[str, str]:
    if NEW in source and NEW2 in source:
        ast.parse(source)
        return source, "ALREADY_PATCHED"
    if source.count(OLD)!=1 or source.count(OLD2)!=1:
        raise RuntimeError("ABORT: source anchors mismatch, no files changed")
    updated=source.replace(OLD,NEW).replace(OLD2,NEW2)
    ast.parse(updated)
    return updated, "PATCH_READY"

def smoke_test(source: str) -> None:
    tree=ast.parse(source)
    needed={"_is_shorts","_primary_dialogue_id","_multi_dialogue_manifest","_primary_outputs"}
    selected=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in needed]
    if {x.name for x in selected}!=needed:
        raise RuntimeError("Cannot extract exact primary-output helpers")
    ctx={"Path":Path,"os":os,"re":re,"json":json}
    exec(compile(ast.Module(body=selected,type_ignores=[]),FILENAME,"exec"),ctx)
    with tempfile.TemporaryDirectory(prefix="rg_903_postrun_") as temp:
        base=Path(temp)
        dest=base/"903"
        dest.mkdir()
        ids=(1,3,4,6)
        outputs=[]
        for i in ids:
            n="RG_EDITED_903_1_R3.xml" if i==1 else f"RG_EDITED_903_{i}.xml"
            p=dest/n
            p.write_text("<xmeml/>",encoding="utf-8")
            (dest/(p.stem+"_UNCENSORED.xml")).write_text("<xmeml/>",encoding="utf-8")
            outputs.append({"index":i,"screenshot":f"903-{i}.jpg","premiere_xml":str(p)})
        manifest={"stream":"903","status":"PARTIAL_REVIEW","dialogue_count":6,
                  "outputs":outputs,"review_holds":[{"index":2},{"index":5}]}
        mp=base/"RG_EDITED_903_MULTI_DIALOGUE.json"
        mp.write_text(json.dumps(manifest),encoding="utf-8")
        result=ctx["_primary_outputs"](dest,[], "903")
        got=[p.name for p in result]
        expected=[Path(x["premiere_xml"]).name for x in outputs]
        if got!=expected:
            raise RuntimeError(f"Partial manifest must expose only 4 canonical XMLs: {got}")
        manifest["review_holds"]=[{"index":1},{"index":5}]
        mp.write_text(json.dumps(manifest),encoding="utf-8")
        if ctx["_primary_outputs"](dest,[], "903"):
            raise RuntimeError("Overlapping hold and complete XML was accepted")
        manifest["status"]="FAILED"
        mp.write_text(json.dumps(manifest),encoding="utf-8")
        if ctx["_primary_outputs"](dest,[], "903"):
            raise RuntimeError("Unverified FAILED manifest was accepted")

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--app",type=Path,default=APP)
    ap.add_argument("--data",type=Path,default=DATA)
    args=ap.parse_args()
    app=args.app
    source_path=app/FILENAME
    ver=app/"rg_studio_version.py"
    if not source_path.is_file() or not ver.is_file():
        raise RuntimeError("Required live Studio files are missing")
    version=ver.read_text(encoding="utf-8-sig",errors="replace")
    if not re.search(r'STUDIO_VERSION\s*=\s*["\']0\.20\.20\.14["\']',version):
        raise RuntimeError("Version not 0.20.20.14; refusing to patch a different Studio")
    original=source_path.read_text(encoding="utf-8-sig")
    patched,state=patch_source(original)
    smoke_test(patched)
    result={"schema":"RG_AUTO_EDIT_QA_PARTIAL_FIX_V1","status":state,
            "tested":True,"applied":False,"media_writes":0,"xml_writes":0}
    if args.apply and state=="PATCH_READY":
        backup=args.data/"release_backups"/("PRE_QA_PARTIAL_FIX_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        shutil.copy2(source_path,backup/FILENAME)
        temp=source_path.with_name(FILENAME+".qa-partial-new")
        try:
            temp.write_text(patched,encoding="utf-8")
            if temp.read_text(encoding="utf-8")!=patched:raise RuntimeError("Write verify mismatch")
            ast.parse(temp.read_text(encoding="utf-8"))
            os.replace(temp,source_path)
            smoke_test(source_path.read_text(encoding="utf-8-sig"))
            result.update(status="APPLIED",applied=True,backup=str(backup/FILENAME))
        except Exception:
            shutil.copy2(backup/FILENAME,source_path)
            raise
        finally:
            temp.unlink(missing_ok=True)
    print("RG_QA_PARTIAL_FIX|"+json.dumps(result,ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
