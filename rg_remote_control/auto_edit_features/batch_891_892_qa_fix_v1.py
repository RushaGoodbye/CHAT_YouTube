#!/usr/bin/env python3
"""Fix manifest-vs-stale-inventory QA for completed RG Auto Edit 891/892.

Dry-run by default. --apply atomically patches rg_studio_postrun.py, saves
all old QA JSONs, reruns QA-only on 891/892, requires PASS for both, and
rolls back source plus QA JSON on any mismatch. Never changes XML or media.
"""
from __future__ import annotations
import argparse
import ast
import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
RUNTIME=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe")
MODULE="rg_studio_postrun.py"
REPORTS=("RG_POSTRUN_QA.json","RG_XML_VERIFY_V51.json","RG_BOUNDARY_QA_V51.json")
TARGETS={"891":{"6"},"892":{"3","5","6"}}

OLD1="""                        identity=_primary_dialogue_id(stream,raw.name)
                        shot=Path(str(row.get('screenshot') or '')).name"""
NEW1="""                        identity=_primary_dialogue_id(stream,raw.name)
                        _legacy_main=(len(rows)==1 and
                                      raw.name.casefold()==f'RG_EDITED_{stream}.xml'.casefold())
                        shot=Path(str(row.get('screenshot') or '')).name"""
OLD2="""                        if (identity is None or match is None or identity!=match.group(1) or identity in ids):
                            good=False;break
                        ids.add(identity)"""
NEW2="""                        if (match is None or (identity is None and not _legacy_main)
                            or (identity is not None and identity!=match.group(1))
                            or (identity or 'MAIN') in ids):
                            good=False;break
                        ids.add(identity or 'MAIN')"""

INVENTORY_METHOD="""
def _rg_current_manifest_inventory(root:Path,stream,outs):
    \"""Return proved current screenshot IDs from a completed manifest, or None.

    A one-dialogue legacy main file RG_EDITED_891.xml is allowed only
    with exactly one screenshot. No old UNCENSORED or inventory guesses.
    \"""
    manifest_path=_multi_dialogue_manifest(root,str(stream))
    if manifest_path is None:return None
    try:
        m=json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))
        rows=m.get('outputs') or []
        if (str(m.get('stream'))!=str(stream)
            or str(m.get('status'))!='DIALOGUES_COMPLETE'
            or int(m.get('dialogue_count') or 0)!=len(rows)
            or not rows or len(outs)!=len(rows)):
            return None
        actual={Path(p).name.casefold():Path(p) for p in outs if Path(p).is_file()}
        if len(actual)!=len(rows):return None
        seen=set();used=set()
        for row in rows:
            if not isinstance(row,dict):return None
            shot=Path(str(row.get('screenshot') or '')).name
            hit=re.fullmatch(re.escape(str(stream))+r'-(\\d+)\\.(?:jpg|jpeg|png)',shot,re.I)
            if hit is None:return None
            sid=hit.group(1)
            filename=Path(str(row.get('premiere_xml') or row.get('xml') or '')).name
            if filename.casefold() not in actual or filename.casefold() in used:
                return None
            used.add(filename.casefold())
            identity=_primary_dialogue_id(stream,filename)
            legacy_single=(len(rows)==1 and filename.casefold()==f'RG_EDITED_{stream}.xml'.casefold())
            if (identity is None and not legacy_single) or (identity is not None and identity!=sid) or sid in seen:
                return None
            seen.add(sid)
        return seen
    except (ValueError,TypeError,OSError,KeyError):
        return None
"""
INVENTORY_METHOD=INVENTORY_METHOD.replace('\\\\d','\\d').replace('\\\\.','\\.')
ANCHOR_FN="def main():"
ANCHOR_USE="    missing_expected=sorted(all_expected-primary_ids"

OVERRIDE="""    # RG_QA_MANIFEST_INVENTORY_V1: current completed manifest outranks stale
    # uncensored variants and old folder inventories. Invalid manifests retain
    # the original strict path; PARTIAL_REVIEW is NOT converted to complete.
    _rg_verified_ids=_rg_current_manifest_inventory(root,a.stream,outs)
    if _rg_verified_ids is not None:
        primary_ids=set(_rg_verified_ids)
        all_expected=set(_rg_verified_ids)
        uncensored_ids=set()
        manifest_expected=set(_rg_verified_ids)
        inventory_expected=set()
"""

def patch_source(source):
    if "_rg_current_manifest_inventory(root:Path,stream,outs)" in source and "RG_QA_MANIFEST_INVENTORY_V1" in source:
        ast.parse(source)
        return source,"ALREADY_PATCHED"
    for i,old in enumerate((OLD1,OLD2,ANCHOR_FN,ANCHOR_USE)):
        if source.count(old)!=1:
            raise RuntimeError(f"Live source anchor {i} count={source.count(old)}, patch aborted")
    result=source.replace(OLD1,NEW1,1).replace(OLD2,NEW2,1)
    result=result.replace(ANCHOR_FN,INVENTORY_METHOD+"\n"+ANCHOR_FN,1)
    result=result.replace(ANCHOR_USE,OVERRIDE+ANCHOR_USE,1)
    ast.parse(result)
    return result,"PATCH_READY"

def smoke_test(source):
    tree=ast.parse(source)
    funcs={k:v for v in tree.body if isinstance(v,ast.FunctionDef) for k in [v.name]}
    need=("_is_shorts","_primary_dialogue_id","_multi_dialogue_manifest","_primary_outputs","_rg_current_manifest_inventory")
    if any(k not in funcs for k in need):
        raise RuntimeError("Cannot isolate current output/manifest validation helpers")
    from tempfile import TemporaryDirectory
    ctx={"Path":Path,"os":os,"re":re,"json":json}
    exec(compile(ast.Module(body=[funcs[k] for k in need],type_ignores=[]),MODULE,"exec"),ctx)
    with TemporaryDirectory(prefix="rg_manifest_qa_") as tmp:
        app=Path(tmp)
        for stream,shots in TARGETS.items():
            folder=app/stream;folder.mkdir()
            rows=[]
            for i,sid in enumerate(sorted(shots,key=int),1):
                name=f'RG_EDITED_{stream}.xml' if stream=="891" else f'RG_EDITED_{stream}_{sid}.xml'
                (folder/name).write_text("<xmeml/>",encoding="utf-8")
                rows.append({"index":i,"screenshot":f'{stream}-{sid}.jpg',"premiere_xml":str(folder/name)})
            manifest={"stream":stream,"status":"DIALOGUES_COMPLETE","dialogue_count":len(rows),"outputs":rows}
            (app/f'RG_EDITED_{stream}_MULTI_DIALOGUE.json').write_text(json.dumps(manifest),encoding="utf-8")
            outs=ctx["_primary_outputs"](folder,[],stream)
            got=ctx["_rg_current_manifest_inventory"](folder,stream,outs)
            if got!=shots:
                raise RuntimeError(f"Manifest fixture {stream} expected {shots}; got {got}")
            manifest["status"]="PARTIAL_REVIEW"
            (app/f'RG_EDITED_{stream}_MULTI_DIALOGUE.json').write_text(json.dumps(manifest),encoding="utf-8")
            if ctx["_rg_current_manifest_inventory"](folder,stream,outs) is not None:
                raise RuntimeError("Partial-review manifest was falsely promoted")

def validate_runtime():
    if not (APP/MODULE).is_file() or not RUNTIME.is_file() or not (APP/"rg_studio_version.py").is_file():
        raise RuntimeError("Installed Studio runtime not found")
    version=(APP/"rg_studio_version.py").read_text(encoding="utf-8-sig")
    if not re.search(r'STUDIO_VERSION\s*=\s*["\x27]0\.20\.20\.14["\x27]',version):
        raise RuntimeError("Unexpected Studio version; source modifications refused")
    for stream,shot_ids in TARGETS.items():
        mf=APP/f'RG_EDITED_{stream}_MULTI_DIALOGUE.json'
        if not mf.is_file():raise RuntimeError(f"No {stream} multi-dialogue manifest")
        data=json.loads(mf.read_text(encoding="utf-8-sig"))
        actual={Path(row.get("screenshot") or "").stem.split("-")[-1] for row in data.get("outputs") or []}
        if data.get("status")!="DIALOGUES_COMPLETE" or actual!=shot_ids:
            raise RuntimeError(f"Unexpected {stream} manifest; abort")
        for row in data["outputs"]:
            if not (APP/stream/Path(row.get("premiere_xml") or "").name).is_file():
                raise RuntimeError(f"Current {stream} XML missing")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    validate_runtime()
    src_path=APP/MODULE;original=src_path.read_text(encoding="utf-8-sig")
    patched,status=patch_source(original)
    smoke_test(patched)
    res={"schema":"RG_AUTO_EDIT_BATCH_891_892_QA_FIX_V1","status":status,
         "verified_fixtures":["891","892"],"media_writes":0,"xml_writes":0,
         "applied":False}
    if not args.apply or status=="ALREADY_PATCHED":
        print("RG_BATCH_891_892_QA_FIX|"+json.dumps(res,ensure_ascii=False),flush=True)
        return
    backup=DATA/"release_backups"/("PRE_BATCH_891_892_QA_"+
           datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(src_path,backup/MODULE)
    existed={}
    for stream in TARGETS:
        for filename in REPORTS:
            rel=f'{stream}/{filename}'
            path=APP/rel;existed[rel]=path.is_file()
            if path.is_file():
                (backup/stream).mkdir(exist_ok=True)
                shutil.copy2(path,backup/rel)
    temporary=src_path.with_name(MODULE+".batchqa-next")
    try:
        temporary.write_text(patched,encoding="utf-8")
        ast.parse(temporary.read_text(encoding="utf-8"))
        os.replace(temporary,src_path)
        for stream,ids in TARGETS.items():
            cmd=[str(RUNTIME),"-u",str(src_path),"--stream",stream,
                 "--folder",str(APP/stream),"--outputs-json","[]"]
            env=os.environ.copy();env["RG_POSTRUN_QA_ONLY"]="1"
            proc=subprocess.run(cmd,cwd=str(APP),env=env,capture_output=True,
                                text=True,encoding="utf-8",errors="replace",timeout=240)
            report_file=APP/stream/"RG_POSTRUN_QA.json"
            if not report_file.is_file():
                raise RuntimeError(f"QA {stream} did not produce a report: {proc.stderr[-300:]}")
            qa=json.loads(report_file.read_text(encoding="utf-8-sig"))
            checks={x.get("name"):x.get("ok") for x in qa.get("checks") or [] if isinstance(x,dict)}
            if (proc.returncode!=0 or qa.get("passed") is not True
                or qa.get("xml_count")!=len(ids) or checks.get("Повнота діалогів") is not True
                or checks.get("Перевірка XML") is not True
                or checks.get("Premiere сумісність") is not True):
                raise RuntimeError(f"QA {stream} not verified: return={proc.returncode}, failed="+
                    repr([x.get("name") for x in qa.get("checks",[]) if not x.get("ok") and x.get("critical")]))
            res[stream]={"qa_passed":True,"xml_count":qa["xml_count"],"expected_screenshots":sorted(ids)}
        res.update(status="APPLIED_QA_PASS",applied=True,backup=str(backup))
    except Exception:
        shutil.copy2(backup/MODULE,src_path)
        for rel,was_present in existed.items():
            dst=APP/rel;src=backup/rel
            if was_present:shutil.copy2(src,dst)
            else:dst.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    print("RG_BATCH_891_892_QA_FIX|"+json.dumps(res,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
