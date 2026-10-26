#!/usr/bin/env python3
"""Read-only 907-1 guest identity evidence for two contradictory clock anchors.

A screen-clock consensus differs from local visual anchor by 123.8 seconds.
Never accepts a clock shift without an actual same-guest face match and never
changes dialogue boundaries, video, audio, cache, XML, or the screenshot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens\907-1.jpg")
SOURCE=Path(r"\\Desktop-v7gg0en\record")
GRID_TIME=4814.8
LOCAL_TIME=4938.5

def verdict(grid,local):
    def strong(data):
        total=int(data.get("samples") or 0)
        current=int(data.get("current_hits") or 0)
        return total>=10 and current>=6 and current/total>=.50 and float(data.get("best_score") or 0)>=.55
    g,l=strong(grid),strong(local)
    if l and not g and int(grid.get("current_hits") or 0)<=1:
        return "LOCAL_GUEST_EVIDENCE_STRONG_NOT_AUTOMATICALLY_APPROVED"
    if g and not l and int(local.get("current_hits") or 0)<=1:
        return "GRID_GUEST_EVIDENCE_STRONG_NOT_AUTOMATICALLY_APPROVED"
    if g and l:return "BOTH_GUEST_CANDIDATES_AMBIGUOUS"
    return "GUEST_CLOCK_CORRECTION_NOT_PROVEN"

def sample(video,ref,center,frame_iter,identity_state):
    start=max(0.,center-55.);end=center+55.
    result={"center_sec":center,"samples":0,"current_hits":0,
            "other_hits":0,"placeholder_hits":0,
            "best_score":0.,"current_times_first":[]}
    for sec,frame in frame_iter(str(video),start,end,sample_fps=.31):
        state,_,score,_,_=identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
        result["samples"]+=1
        if state=="CURRENT":
            result["current_hits"]+=1
            if len(result["current_times_first"])<6:
                result["current_times_first"].append(round(float(sec),2))
        elif state in ("PLACEHOLDER","UNKNOWN"):
            result["placeholder_hits"]+=1
        else:
            result["other_hits"]+=1
        result["best_score"]=round(max(result["best_score"],float(score)),4)
    return result

def main():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    report={
        "schema":"RG_907_1_CONFLICTING_CLOCK_FACE_SHADOW_V1",
        "read_only":True,"auto_reanchor":False,
        "video_writes":0,"xml_writes":0,"queue_writes":0,
        "screenshot_present":SCREEN.is_file(),
        "consensus_sec":GRID_TIME,
        "local_visual_candidate_sec":LOCAL_TIME,
        "difference_sec":round(LOCAL_TIME-GRID_TIME,2)
    }
    if not report["screenshot_present"]:
        report["verdict"]="MISSING_SCREENSHOT"
    else:
        image=cv2.imread(str(SCREEN))
        if image is None:
            report["verdict"]="UNREADABLE_SCREENSHOT"
        else:
            ref,meta=_reference_guest_descriptor(image)
            report["reference"]={k:v for k,v in meta.items() if k!="embedding"}
            if ref is None:
                report["verdict"]="NO_REFERENCE_GUEST_FACE_IN_907_1"
            else:
                video,_,_=resolve_video(str(SOURCE),"907")
                report["consensus"]=sample(video,ref,GRID_TIME,_iter_window_ffmpeg,_frame_identity_state)
                report["local"]=sample(video,ref,LOCAL_TIME,_iter_window_ffmpeg,_frame_identity_state)
                report["verdict"]=verdict(report["consensus"],report["local"])
    print("RG_907_GUEST_CLOCK_SHADOW|"+json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
