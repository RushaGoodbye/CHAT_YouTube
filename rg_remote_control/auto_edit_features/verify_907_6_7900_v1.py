#!/usr/bin/env python3
"""Read-only fine face/video verification of 907-6 candidate around 7900 seconds."""
from __future__ import annotations
import json,sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _iter_window_ffmpeg,_probe_duration,_best_local_match
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    video,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not video or not Path(video).is_file():raise RuntimeError("Missing original 907 video")
    shot=cv2.imread(str(SCREEN/"907-6.jpg"))
    if shot is None:raise RuntimeError("Missing 907-6.jpg")
    ref,meta=_reference_guest_descriptor(shot)
    if ref is None:raise RuntimeError("No guest reference")
    hits=[]; n=0
    for sec,frame in _iter_window_ffmpeg(str(video),7770,8050,sample_fps=1.0):
        n+=1
        state,_,score,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
        if state=="CURRENT":hits.append((round(float(sec),2),round(float(score),4)))
    matches=[]
    for center in (7880,7900,7913.75,7930):
        m=_best_local_match(str(video),shot,center,_probe_duration(video),progress_cb=None,coarse_radius_sec=18.)
        matches.append({"center":center,"time":round(float(m.get("time",center)),2),"score":round(float(m.get("score",0)),4)})
    return {"schema":"RG_907_6_FINE_V1","read_only":True,"media_writes":0,"xml_writes":0,
            "frames":n,"face_hits":len(hits),"face_peaks":sorted(hits,key=lambda x:x[1],reverse=True)[:12],
            "visual":matches,"release":False}
if __name__=="__main__":
    print("RG907_6_FINE|"+json.dumps(run(),ensure_ascii=False),flush=True)
