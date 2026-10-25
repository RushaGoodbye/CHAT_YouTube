#!/usr/bin/env python3
"""Review-only reconciliation for REAL neighbour XML overlaps in 901 and 905.

Dry-run first. --apply backs up and atomically changes only studio_batch_queue.json.
No source XMLs, QA, manifest, video or audio can be edited or approved.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import shutil
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
STATE=Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))/"RG_Auto_Edit"/"studio_batch_queue.json"
PAIRS={"901":{(4,5):4843,(5,6):3883},"905":{(1,2):201}}

def issues_for_stream(stream,manifest,qa,boundary):
    if (str(manifest.get("stream"))!=stream or manifest.get("status")!="DIALOGUES_COMPLETE"
        or len(manifest.get("outputs") or [])!=int(manifest.get("dialogue_count") or 0)
        or qa.get("stream")!=stream or qa.get("passed") is not False
        or qa.get("xml_count")!=len(manifest.get("outputs") or [])):
        raise RuntimeError(f"{stream} manifest / QA not in expected guarded state")
    if not all(bool(x.get("premiere_xml")) for x in manifest.get("outputs") or []):
        raise RuntimeError("Missing explicit final XML paths in manifest")
    check={x.get("name"):x for x in qa.get("checks") or [] if isinstance(x,dict)}
    for name in ("Перевірка XML","Контроль меж"):
        c=check.get(name)
        if not c or c.get("ok") is not False or c.get("critical") is not True:
            raise RuntimeError(f"{stream} critical {name} failure not evidenced")
    if boundary.get("passed") is not False:
        raise RuntimeError(f"{stream} boundary report is not a failure")
    actual={}
    for issue in boundary.get("issues") or []:
        if not isinstance(issue,dict) or issue.get("code")!="NEIGHBOUR_XML_SOURCE_OVERLAP":
            raise RuntimeError(f"{stream} unexpected boundary issue")
        pair=(int(issue.get("left") or 0),int(issue.get("right") or 0))
        if pair in actual:raise RuntimeError("Duplicate boundary issue")
        actual[pair]=int(issue.get("frames") or 0)
    if actual!=PAIRS[stream]:
        raise RuntimeError(f"{stream} boundary issue set changed; refuse stale review label")
    msg="; ".join(f"{a}→{b}: {frames} кадрів" for (a,b),frames in sorted(actual.items()))
    return f"Перетин сусідніх діалогів: {msg} • XML збережено"

def plan(state,evidence):
    if state.get("running") or state.get("paused"):
        raise RuntimeError("Active queue: refusing persisted UI state changes")
    if state.get("schema")!="RG_STUDIO_BATCH_UI_V2":
        raise RuntimeError("Unexpected queue state schema")
    rows=state.get("rows") or []
    out=json.loads(json.dumps(state,ensure_ascii=False))
    applied=[]
    for stream in PAIRS:
        found=[x for x in out.get("rows") or [] if isinstance(x,dict) and str(x.get("stream"))==stream]
        if len(found)!=1:raise RuntimeError(f"Missing or duplicate {stream} queue row")
        row=found[0]
        label=issues_for_stream(stream,*evidence[stream])
        if row.get("status")=="ПЕРЕВІРКА" and row.get("stage")=="BOUNDARY_REVIEW":
            if row.get("detail")!=label:raise RuntimeError("Unexpected prior review label")
            continue
        if row.get("status")!="ГОТОВО" or row.get("stage")!="CHECKPOINT":
            raise RuntimeError(f"Unexpected {stream} status: refusing to overwrite")
        row.update(status="ПЕРЕВІРКА",stage="BOUNDARY_REVIEW",progress="99%",eta="—",detail=label)
        applied.append(stream)
    return out,applied

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--apply",action="store_true");args=ap.parse_args()
    if not STATE.is_file():raise RuntimeError("Queue state missing")
    old=STATE.read_text(encoding="utf-8-sig")
    state=json.loads(old)
    evidence={}
    for stream in PAIRS:
        base=APP/stream
        paths=(APP/f"RG_EDITED_{stream}_MULTI_DIALOGUE.json",
               base/"RG_POSTRUN_QA.json",base/"RG_BOUNDARY_QA_V51.json")
        if not all(x.is_file() for x in paths):
            raise RuntimeError(f"Evidence files missing: {stream}")
        evidence[stream]=tuple(json.loads(x.read_text(encoding="utf-8-sig")) for x in paths)
    planned,change=plan(state,evidence)
    result={"schema":"RG_AUTO_EDIT_BOUNDARY_QUEUE_REVIEW_V1","status":"PATCH_READY" if change else "ALREADY_REVIEW",
            "streams":change,"applied":False,"media_writes":0,"xml_writes":0,"qa_writes":0}
    if args.apply and change:
        backup=DATA/"release_backups"/("PRE_BOUNDARY_QUEUE_REVIEW_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        saved=backup/STATE.name
        shutil.copy2(STATE,saved)
        proposed=STATE.with_suffix(STATE.suffix+".boundary-next")
        try:
            if STATE.read_text(encoding="utf-8-sig")!=old:
                raise RuntimeError("Queue modified concurrently")
            proposed.write_text(json.dumps(planned,ensure_ascii=False,indent=2),encoding="utf-8")
            check,changes_again=plan(json.loads(proposed.read_text(encoding="utf-8")),evidence)
            if changes_again:raise RuntimeError("Reconciled queue did not validate")
            os.replace(proposed,STATE)
            result.update(status="APPLIED",applied=True,backup=str(saved))
        except Exception:
            shutil.copy2(saved,STATE)
            raise
        finally:
            proposed.unlink(missing_ok=True)
    print("RG_BOUNDARY_REVIEW_QUEUE|"+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
