#!/usr/bin/env python3
"""Reconcile the stale 903 queue display to verified PARTIAL_REVIEW, never COMPLETE.

Default dry-run; --apply backs up ONLY the batch UI JSON. No video, XML,
backend, cache, manifest or QA report is modified. The Studio UI can reload
the preserved queue entry on a guarded restart.
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
STATE=Path(os.getenv("LOCALAPPDATA") or str(Path.home()))/"RG_Auto_Edit"/"studio_batch_queue.json"

REQUIRED=("XML створено","XML існують","XML синтаксис",
          "Аудіо ORIGINAL SOURCE","Перевірка XML","Контроль меж",
          "Premiere сумісність")

def proof(manifest,qa):
    rows=manifest.get("outputs") or []
    holds=manifest.get("review_holds") or []
    expected=int(manifest.get("dialogue_count") or 0)
    found={int(x.get("index") or 0) for x in rows if isinstance(x,dict)}
    held={int(x.get("index") or 0) for x in holds if isinstance(x,dict)}
    check={x.get("name"):x.get("ok") for x in qa.get("checks",[]) if isinstance(x,dict)}
    valid=(manifest.get("stream")=="903" and manifest.get("status")=="PARTIAL_REVIEW"
           and expected==6 and found=={1,3,4,6} and held=={2,5}
           and len(rows)==4 and len(holds)==2 and qa.get("stream")=="903"
           and qa.get("passed") is False and qa.get("xml_count")==4
           and all(check.get(x) is True for x in REQUIRED)
           and all(str(h.get("status"))=="HOLD_FOR_REVIEW" for h in holds))
    if not valid:raise RuntimeError("Real 903 manifest / QA does not prove partial review")
    return "Готові XML: 4/6 • перевірка гостя: 2, 5"

def plan(state,manifest,qa):
    if state.get("running") or state.get("paused"):
        raise RuntimeError("Batch running/paused: no queue edits permitted")
    if state.get("schema")!="RG_STUDIO_BATCH_UI_V2":
        raise RuntimeError("Unexpected batch-state schema")
    label=proof(manifest,qa)
    rows=state.get("rows") or []
    matches=[r for r in rows if isinstance(r,dict) and str(r.get("stream"))=="903"]
    if len(matches)!=1:
        raise RuntimeError("Exactly one 903 queue row required")
    item=matches[0]
    if item.get("status")=="ПЕРЕВІРКА" and item.get("stage")=="IDENTITY_REVIEW":
        return state,"ALREADY_REVIEW"
    if item.get("status")!="ПОМИЛКА" or item.get("stage")!="ERROR":
        raise RuntimeError("Unexpected queue 903 stage: refusing to overwrite")
    new=json.loads(json.dumps(state,ensure_ascii=False))
    row=next(r for r in new["rows"] if str(r.get("stream"))=="903")
    row.update(status="ПЕРЕВІРКА",stage="IDENTITY_REVIEW",progress="67%",
               eta="—",detail=label)
    return new,"PATCH_READY"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    if not STATE.is_file():raise RuntimeError("Batch state missing")
    if not (APP/"RG_EDITED_903_MULTI_DIALOGUE.json").is_file():raise RuntimeError("903 manifest missing")
    if not (APP/"903"/"RG_POSTRUN_QA.json").is_file():raise RuntimeError("903 QA missing")
    manifest=json.loads((APP/"RG_EDITED_903_MULTI_DIALOGUE.json").read_text(encoding="utf-8-sig"))
    qa=json.loads((APP/"903"/"RG_POSTRUN_QA.json").read_text(encoding="utf-8-sig"))
    old=STATE.read_text(encoding="utf-8-sig")
    current=json.loads(old)
    proposed,status=plan(current,manifest,qa)
    answer={"schema":"RG_903_QUEUE_REVIEW_RECONCILE_V1","status":status,
            "applied":False,"media_writes":0,"xml_writes":0,
            "queue_running":current.get("running",False)}
    if args.apply and status=="PATCH_READY":
        backup=DATA/"release_backups"/("PRE_903_QUEUE_REVIEW_"+
                 datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        saved=backup/"studio_batch_queue.json"
        shutil.copy2(STATE,saved)
        newfile=STATE.with_suffix(STATE.suffix+".review-next")
        try:
            # Fail closed if UI concurrently edited its state after the snapshot.
            if STATE.read_text(encoding="utf-8-sig")!=old:
                raise RuntimeError("Queue state changed concurrently")
            newfile.write_text(json.dumps(proposed,ensure_ascii=False,indent=2),encoding="utf-8")
            if plan(json.loads(newfile.read_text(encoding="utf-8")),manifest,qa)[1]!="ALREADY_REVIEW":
                raise RuntimeError("Written queue review state failed audit")
            os.replace(newfile,STATE)
            answer.update(status="APPLIED",applied=True,backup=str(saved))
        except Exception:
            shutil.copy2(saved,STATE)
            raise
        finally:
            newfile.unlink(missing_ok=True)
    print("RG_903_QUEUE_REVIEW|"+json.dumps(answer,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
