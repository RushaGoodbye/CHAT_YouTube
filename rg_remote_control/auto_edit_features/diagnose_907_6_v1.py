#!/usr/bin/env python3
"""Strict read-only independent two-window evidence for screenshot 907-6."""
from __future__ import annotations
import json, sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
CENTERS=(8827.8,8954.8)
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _best_local_match,_probe_duration,_iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    source,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not source or not Path(source).is_file():
        raise RuntimeError("907 original video unavailable")
    screenshot=SCREEN/"907-6.jpg"
    img=cv2.imread(str(screenshot))
    if img is None:raise RuntimeError("907-6 screenshot unavailable")
    ref,meta=_reference_guest_descriptor(img)
    if ref is None:raise RuntimeError("907-6 guest reference unavailable")
    duration=float(_probe_duration(source))
    out=[]
    for center in CENTERS:
        result=_best_local_match(str(source),img,center,duration,progress_cb=None,coarse_radius_sec=38.)
        t=float(result.get("time",center))
        score=float(result.get("score",0))
        hits=0; peak=0.
        for sec,frame in _iter_window_ffmpeg(str(source),max(0,t-20),min(duration,t+20),sample_fps=.40):
            state,_,value,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            if state=="CURRENT":
                hits+=1
                peak=max(peak,float(value))
        out.append({"window_center":center,"time":round(t,2),"visual_score":round(score,4),
                    "guest_face_hits":hits,"guest_face_peak":round(peak,4),
                    "independent_proof":score>=.52 and hits>=2 and peak>=.60})
    proven=[x for x in out if x["independent_proof"]]
    return {"schema":"RG_907_6_TWO_WINDOW_PROOF_V1","read_only":True,
            "xml_writes":0,"media_writes":0,"queue_writes":0,
            "status":"ONE_PROVEN" if len(proven)==1 else "NEEDS_REVIEW",
            "results":out,"auto_release":False}
if __name__=="__main__":
    print("RG_907_6_PROOF|"+json.dumps(run(),ensure_ascii=False),flush=True)
