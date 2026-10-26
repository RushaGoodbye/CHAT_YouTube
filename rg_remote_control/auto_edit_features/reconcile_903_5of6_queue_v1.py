#!/usr/bin/env python3
"""Align idle Studio queue status with verified selective-retry result 903 5/6.

No media or XML writes. Require exact live manifest+files and idle queue, only
update the 903 UI row. Backup+atomic compare-before-replace, never promote DONE.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
UI_STATE=Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))/"RG_Auto_Edit"/"studio_batch_queue.json"
OLD_LABEL="Готові XML: 4/6 • перевірка гостя: 2, 5"
NEW_LABEL="Готові XML: 5/6 • перевірка гостя: 5"

def valid_manifest(doc):
    outs=doc.get("outputs") or []
    holds=doc.get("review_holds") or []
    if (str(doc.get("stream"))!="903" or doc.get("status")!="PARTIAL_REVIEW"
        or int(doc.get("dialogue_count") or 0)!=6 or len(outs)!=5 or
        len(holds)!=1 or
        {int(x.get("index") or 0) for x in outs}!={1,2,3,4,6} or
        {int(x.get("index") or 0) for x in holds}!={5}):
        raise RuntimeError("903 latest actual manifest does not prove 5/6")
    if not all(Path(str(x.get("xml") or "")).is_file() for x in outs):
        raise RuntimeError("Some 903 completed XML files are missing")
    if any(str(x.get("status"))!="HOLD_FOR_REVIEW" for x in holds):
        raise RuntimeError("Unexpected held-guest identity status")
    return True

def proposed_state(state,manifest):
    valid_manifest(manifest)
    if state.get("schema")!="RG_STUDIO_BATCH_UI_V2":
        raise RuntimeError("Unknown queue schema")
    if state.get("running") or state.get("paused"):
        raise RuntimeError("Live/paused queue cannot be edited")
    rows=state.get("rows") or []
    targets=[r for r in rows if str(r.get("stream"))=="903"]
    if len(targets)!=1:raise RuntimeError("903 UI row not unique")
    item=targets[0]
    if (item.get("status")!="ПЕРЕВІРКА" or
        item.get("stage")!="IDENTITY_REVIEW"):
        raise RuntimeError("Queue 903 row not in held-identity state")
    if item.get("detail")==NEW_LABEL and item.get("progress")=="83%":
        return state,"ALREADY_CURRENT"
    if item.get("detail")!=OLD_LABEL:
        raise RuntimeError("Unexpected queue detail, concurrent edit may exist")
    updated=json.loads(json.dumps(state,ensure_ascii=False))
    row=next(r for r in updated["rows"] if str(r.get("stream"))=="903")
    row.update(detail=NEW_LABEL,progress="83%",status="ПЕРЕВІРКА",
               stage="IDENTITY_REVIEW",eta="—")
    return updated,"PATCH_READY"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    opt=ap.parse_args()
    if not UI_STATE.is_file():raise RuntimeError("Studio queue state missing")
    manifest_file=APP/"RG_EDITED_903_MULTI_DIALOGUE.json"
    if not manifest_file.is_file():raise RuntimeError("903 current manifest missing")
    manifest=json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    original=UI_STATE.read_bytes()
    state=json.loads(original.decode("utf-8-sig"))
    next_state,status=proposed_state(state,manifest)
    result={"schema":"RG_903_5OF6_QUEUE_RECONCILE_V1","status":status,
            "applied":False,"media_writes":0,"xml_writes":0,
            "queue_running":bool(state.get("running")),
            "dialogues_ready":5,"remaining_review":[5],
            "studio_restart_required_to_refresh_existing_window":True}
    if opt.apply and status=="PATCH_READY":
        dst=DATA/"release_backups"/("PRE_903_QUEUE_5OF6_"+
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        dst.mkdir(parents=True,exist_ok=False)
        backup=dst/UI_STATE.name
        shutil.copy2(UI_STATE,backup)
        tmp=UI_STATE.with_suffix(UI_STATE.suffix+".903-next")
        try:
            if UI_STATE.read_bytes()!=original:
                raise RuntimeError("Queue changed since preflight: no writes")
            tmp.write_text(json.dumps(next_state,ensure_ascii=False,indent=2),
                           encoding="utf-8")
            if proposed_state(json.loads(tmp.read_text(encoding="utf-8")),
                              manifest)[1]!="ALREADY_CURRENT":
                raise RuntimeError("Queue update validation failed")
            os.replace(tmp,UI_STATE)
            result.update(status="APPLIED",applied=True,backup=str(backup))
        except Exception:
            if UI_STATE.read_bytes()==original:
                pass
            else:
                # Do not overwrite newer concurrent GUI state with our backup.
                print("RG_903_UI_RECONCILE|CONCURRENT_UPDATE_CHECK",flush=True)
            raise
        finally:
            tmp.unlink(missing_ok=True)
    result["queue_907"]=[
        {"status":r.get("status"),"stage":r.get("stage"),
         "detail":str(r.get("detail") or "")[:180]}
        for r in state.get("rows") or [] if str(r.get("stream"))=="907"]
    source=Path(r"\\Desktop-v7gg0en\record")
    result["stream_907"]={
        "manifest_present":(APP/"RG_EDITED_907_MULTI_DIALOGUE.json").is_file(),
        "video_candidates":len(list(source.glob("907.*"))) if source.is_dir() else None,
        "screenshots":len(list((source/"Screens").glob("907-*.jpg"))) if (source/"Screens").is_dir() else None,
        "audio_candidates":len(list((source/"sound").glob("907.*"))) if (source/"sound").is_dir() else None,
    }
    print("RG_903_UI_RECONCILE|"+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
