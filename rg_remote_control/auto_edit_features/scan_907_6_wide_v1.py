#!/usr/bin/env python3
"""Bounded full-source guest-identity rescue, read-only, no release."""
from __future__ import annotations
import json,sys,math
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
FPS=.20
MAX_FRAMES=4500
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _probe_duration,_iter_window_ffmpeg,_best_local_match
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    source,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not source or not Path(source).is_file():raise RuntimeError("907 video missing")
    img=cv2.imread(str(SCREEN/"907-6.jpg"))
    if img is None:raise RuntimeError("907-6 screenshot missing")
    ref,meta=_reference_guest_descriptor(img)
    if ref is None:raise RuntimeError("907-6 guest reference unavailable")
    duration=float(_probe_duration(source))
    if not 1000<duration<22000:raise RuntimeError("Unexpected source duration")
    if math.ceil(duration*FPS)>MAX_FRAMES:raise RuntimeError("Scan frame budget exceeded")
    candidates=[];current=0;count=0
    for t,frame in _iter_window_ffmpeg(str(source),0,duration,sample_fps=FPS):
        count+=1
        if count>MAX_FRAMES:raise RuntimeError("Frame budget exceeded")
        state,_,score,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
        if state=="CURRENT":
            current+=1
            candidates.append((round(float(t),2),round(float(score),4)))
    candidates.sort(key=lambda x:x[1],reverse=True)
    groups={}
    for t,s in candidates:
        bucket=int(t//90)
        row=groups.setdefault(bucket,{"hits":0,"peak":0.,"strongest_sec":t})
        row["hits"]+=1
        if s>row["peak"]:
            row["peak"]=s;row["strongest_sec"]=t
    shortlist=sorted(groups.items(),key=lambda kv:(kv[1]["hits"],kv[1]["peak"]),reverse=True)[:8]
    proofs=[]
    for bucket,row in shortlist:
        center=row["strongest_sec"]
        best=_best_local_match(str(source),img,center,duration,progress_cb=None,coarse_radius_sec=45.)
        proofs.append({"bucket":bucket,"face_hits":row["hits"],"face_peak":round(row["peak"],4),
                       "face_strongest":center,"visual_time":round(float(best.get("time",center)),2),
                       "visual_score":round(float(best.get("score",0)),4)})
    return {"schema":"RG_907_6_WIDE_SCAN_V1","read_only":True,"xml_writes":0,
            "media_writes":0,"queue_writes":0,"duration":duration,"frames":count,
            "guest_matches":current,"top_clusters":proofs,"release":False}
if __name__=="__main__":
    print("RG907_6_WIDE|"+json.dumps(run(),ensure_ascii=False),flush=True)
