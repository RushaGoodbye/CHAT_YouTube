#!/usr/bin/env python3
"""Read-only final independent source-frame, identity and chronology audit for stream 907."""
import json,sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
ANCHORS={1:4586.25,2:5348.25,3:6737.39,4:7609.32,5:7851.75,6:7913.75,7:7979.25,8:8715.75}
def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _probe_duration,_best_local_match,_iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    video,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not video or not Path(video).is_file():raise RuntimeError("Missing original video")
    duration=float(_probe_duration(video))
    rows=[]
    for ix,anchor in ANCHORS.items():
        im=cv2.imread(str(SCREEN/f"907-{ix}.jpg"))
        if im is None:raise RuntimeError(f"Missing screenshot {ix}")
        ref,_=_reference_guest_descriptor(im)
        if ref is None:raise RuntimeError(f"No guest face {ix}")
        match=_best_local_match(str(video),im,anchor,duration,progress_cb=None,coarse_radius_sec=23.)
        time=float(match.get("time",0))
        score=float(match.get("score",0))
        hits=0;strong=0;peak=0.
        for sec,frame in _iter_window_ffmpeg(str(video),max(0,time-13),min(duration,time+13),sample_fps=.8):
            state,_,val,_,_=_frame_identity_state(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            if state=="CURRENT":
                hits+=1;peak=max(peak,float(val))
                if float(val)>=.5:strong+=1
        visual=score>=.6 and abs(time-anchor)<=23
        face=hits>=2 and strong>=2 and peak>=.6
        row={"index":ix,"expected":anchor,"matched":round(time,2),"visual_score":round(score,4),
             "face_hits":hits,"strong_hits":strong,"peak":round(peak,4),"visual_ok":visual,
             "face_ok":face,"verified":visual and face}
        rows.append(row)
        print("RG907|ANCHOR_QA|"+json.dumps(row),flush=True)
    ordered=all(a["matched"]<b["matched"] for a,b in zip(rows,rows[1:]))
    return {"schema":"RG907_EIGHT_ANCHOR_QA_V1","read_only":True,"media_writes":0,
            "xml_writes":0,"queue_writes":0,"chronology_ok":ordered,
            "all_anchors_verified":ordered and all(x["verified"] for x in rows),
            "boundary_qa_pending":True,"production_release":False,"anchors":rows}
if __name__=="__main__":
    print("RG907|EIGHT_ANCHOR_RESULT|"+json.dumps(run()),flush=True)
