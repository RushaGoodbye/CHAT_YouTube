#!/usr/bin/env python3
"""One selective 903-2 replay, with proven guest-time re-anchor and rollback.

This is opt-in only via the restricted Windows Actions job, not part of regular
Studio start.  Never edits original media or prior finished Premiere XMLs.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=APP/"RG_EDITED_903_MULTI_DIALOGUE.json"
SHOT=Path(r"\\Desktop-v7gg0en\record\Screens\903-2.jpg")
OLD_ANCHOR=3953.5
NEW_ANCHOR=3608.65
CAPTURE=(3450.,3820.)
LEGACY=(3535.,3740.)

def reanchor(original, parent, match, previous_match=None, next_match=None):
    row=original(parent,match,previous_match=previous_match,next_match=next_match)
    if str(match.get("screenshot") or "")!="903-2.jpg":
        return row
    old=float(row.get("identity_context",{}).get("current_anchor_sec",-1))
    if abs(old-OLD_ANCHOR)>4:
        raise RuntimeError("Refusing re-anchor: screenshot clock evidence changed")
    row=copy.deepcopy(row)
    ctx=row["identity_context"]
    ctx["current_anchor_sec"]=NEW_ANCHOR
    ctx["legacy_interval"]={
        "start":LEGACY[0],"end":LEGACY[1],
        "duration":LEGACY[1]-LEGACY[0],"screenshots":["903-2.jpg"]}
    rng={"start":CAPTURE[0],"end":CAPTURE[1],
         "duration":CAPTURE[1]-CAPTURE[0],"screenshots":["903-2.jpg"]}
    ctx["capture_interval"]=dict(rng)
    row["selected_ranges"]=[rng]
    row["selected_total_sec"]=rng["duration"]
    row["rg_guest_anchor_recovery"]="PROVEN_903_2_CURRENT_GUEST_EARLY"
    return row

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def manifest_gate(doc):
    if (doc.get("stream")!="903" or doc.get("status")!="PARTIAL_REVIEW"
        or doc.get("dialogue_count")!=6 or
        {int(x["index"]) for x in doc.get("review_holds",[])}!={2,5} or
        {int(x["index"]) for x in doc.get("outputs",[])}!={1,3,4,6}):
        raise RuntimeError("903 original manifest changed; refusing selective replay")
    for row in doc["outputs"]:
        if not Path(str(row["xml"])).is_file():
            raise RuntimeError("Original completed XML missing")
    return {int(row["index"]):sha256(Path(row["xml"])) for row in doc["outputs"]}

def visual_proof(video):
    import cv2
    from rg_clock_selector import _iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    image=cv2.imread(str(SHOT))
    ref,meta=_reference_guest_descriptor(image)
    if ref is None or meta.get("mode")!="RIGHT_WINDOW":
        raise RuntimeError("903-2 screenshot identity reference missing")
    def window(start,end):
        total=0;current=0;best=0.
        for t,frame in _iter_window_ffmpeg(str(video),start,end,sample_fps=.28):
            state,similarities,score,nfaces,emb=_frame_identity_state(
                frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            total+=1
            current+=int(state=="CURRENT")
            best=max(best,float(score))
        return {"samples":total,"current_hits":current,"best_score":round(best,4)}
    early=window(3593.5,3650.)
    wrong=window(3880.,3990.)
    if early["samples"]<8 or early["current_hits"]<6 or early["best_score"]<.55:
        raise RuntimeError("Early 903-2 guest evidence is insufficient")
    if wrong["samples"]<8 or wrong["current_hits"]>1:
        raise RuntimeError("Old anchor contains guest or lacks counter-evidence")
    return {"early":early,"incorrect_anchor":wrong,"reanchor_sec":NEW_ANCHOR}

def main():
    sys.path.insert(0,str(APP))
    if not ROOT.is_file():raise RuntimeError("903 manifest missing")
    doc=json.loads(ROOT.read_text(encoding="utf-8-sig"))
    original_hashes=manifest_gate(doc)
    code=APP/"rg_multi_dialogue.py"
    if "RG_BATCH_SELECTIVE_RETRY_V1" not in code.read_text(encoding="utf-8-sig"):
        raise RuntimeError("Selective retry preserve-manifest guard is not installed")
    from rg_server_resolver import resolve_video
    launch=doc.get("launch_args") or {}
    if str(launch.get("video_stream"))!="903" or str(launch.get("audio_stream"))!="903":
        raise RuntimeError("Source stream arguments differ from original")
    video,_,_=resolve_video(str(launch["video_root"]),"903")
    proof=visual_proof(video)
    print("RG_903_2_PROOF|"+json.dumps(proof),flush=True)
    backup_dir=DATA/"release_backups"/("REPLAY_903_2_"+time.strftime("%Y%m%d_%H%M%S"))
    backup_dir.mkdir(parents=True,exist_ok=False)
    old=backup_dir/ROOT.name
    shutil.copy2(ROOT,old)
    args=[]
    for name in ("video_root","audio_root","screen_root","video_stream",
                 "audio_stream","config","model","device","silence_db",
                 "clock_window","clock_step","stream_start"):
        if name not in launch:raise RuntimeError("Original launch argument missing: "+name)
        args.extend(["--"+name.replace("_","-"),str(launch[name])])
    args.extend(["--output",str(doc["requested_output"])])
    os.environ["RG_ONLY_DIALOGUE_INDEXES"]="2"
    os.environ["RG_FORCE_SELECTED_DIALOGUES"]="1"
    os.environ.pop("RG_ONLY_DIALOGUE_INDEX",None)
    sys.argv=[str(code),*args]
    import rg_multi_dialogue as montage
    original=montage._job_found
    montage._job_found=lambda parent,match,previous_match=None,next_match=None:reanchor(
        original,parent,match,previous_match=previous_match,next_match=next_match)
    try:
        montage.main()
        after=json.loads(ROOT.read_text(encoding="utf-8-sig"))
        completed={int(x["index"]):x for x in after.get("outputs",[])}
        held={int(x["index"]) for x in after.get("review_holds",[])}
        if held not in ({5},{2,5}) or set(completed)|held!=set(range(1,7)):
            raise RuntimeError("Selective 903 replay produced invalid dialogue coverage")
        if any(sha256(Path(completed[i]["xml"]))!=h for i,h in original_hashes.items()):
            raise RuntimeError("Unselected dialogue XML changed")
        print("RG_903_2_REPLAY|"+json.dumps({
            "status":"PASS" if 2 in completed else "STILL_HELD",
            "completed":sorted(completed),"held":sorted(held),
            "preserved_xml_ids":sorted(original_hashes),
            "manifest_backup":str(old),"reanchored_seconds":NEW_ANCHOR,
            "source_media_writes":0},ensure_ascii=False),flush=True)
    except BaseException:
        shutil.copy2(old,ROOT)
        print("RG_903_2_REPLAY|ROLLBACK_MANIFEST|"+str(old),flush=True)
        raise

if __name__=="__main__":
    main()
