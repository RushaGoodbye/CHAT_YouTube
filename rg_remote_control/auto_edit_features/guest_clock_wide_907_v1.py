#!/usr/bin/env python3
"""907 guest anchor broad-but-bounded evidence; strictly read-only.

Compare screenshot 907-1/2 identities in the two video-hour candidate regions.
Captures ONLY time and numeric scores, no raw video, images or embeddings.
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
FPS=.16
HALF_WINDOW=720.
MAX_FRAME_BUDGET=510

def windows_from_clock(clock_values, video_duration, candidate_from_clock):
    centers=[]
    for value in clock_values:
        for hour in (20,21):
            t=float(candidate_from_clock(value,hour))
            if -HALF_WINDOW<=t<=video_duration+HALF_WINDOW:
                centers.append((str(hour),round(t,2)))
    if not centers:
        return []
    # Use first screenshot's predictions; second shot verifies relative timing.
    centers=centers[:2]
    return [
        {"hour":label,"clock_candidate_sec":center,
         "start":round(max(0.,center-HALF_WINDOW),2),
         "end":round(min(video_duration,center+HALF_WINDOW),2)}
        for label,center in centers
    ]

def summarize_frames(frames, refs, classifier):
    stats={str(k):{"current":0,"other":0,"placeholder":0,
                   "top_score":0.,"matched_times_first":[],"strongest_time":None}
           for k in refs}
    count=0
    for t,frame in frames:
        count+=1
        if count>MAX_FRAME_BUDGET:raise RuntimeError("Bounded 907 scan budget exceeded")
        for k,ref in refs.items():
            state,sims,score,nfaces,other=classifier(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            row=stats[str(k)]
            if state=="CURRENT":
                row["current"]+=1
                if len(row["matched_times_first"])<10:row["matched_times_first"].append(round(float(t),2))
            elif state=="OTHER_FACE":row["other"]+=1
            else:row["placeholder"]+=1
            score=float(score) if math.isfinite(float(score)) else 0.
            if score>row["top_score"]:
                row["top_score"]=round(score,3)
                row["strongest_time"]=round(float(t),2)
    return {"frames":count,"guests":stats}

def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import (read_clock_from_screenshot,_candidate_time,
                                  _probe_duration,_iter_window_ffmpeg)
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    path,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not path or not Path(path).is_file():
        raise RuntimeError("Missing 907 original source")
    duration=float(_probe_duration(path))
    refs={}
    clock_values=[]
    faces={}
    for ix in (1,2):
        shot=SCREEN/f"907-{ix}.jpg"
        if not shot.is_file():continue
        img=cv2.imread(str(shot))
        if img is None:continue
        ref,meta=_reference_guest_descriptor(img)
        faces[str(ix)]={k:v for k,v in meta.items() if k!="embedding"}
        clock=read_clock_from_screenshot(shot)
        if ix==1:
            clock_values.append(float(clock["seconds_of_day"]))
        if ref is not None:refs[ix]=ref
    if not refs or not clock_values:
        raise RuntimeError("No valid guest or OCR reference for bounded scan")
    spans=windows_from_clock(clock_values,duration,_candidate_time)
    if len(spans)!=2:
        raise RuntimeError("Expected two clock-hour candidate windows, refusing unbounded scan")
    reports=[]
    for span in spans:
        s=summarize_frames(_iter_window_ffmpeg(str(path),span["start"],span["end"],sample_fps=FPS),
                           refs,_frame_identity_state)
        reports.append({**span,**s})
    return {"schema":"RG_907_GUEST_CLOCK_WIDE_V1",
            "read_only":True,"media_writes":0,"xml_writes":0,"queue_writes":0,
            "stream":"907","guest_references":faces,"spans":reports,
            "auto_release":False,"max_frame_budget":MAX_FRAME_BUDGET}

if __name__=="__main__":
    print("RG_907_WIDE_GUEST_EVIDENCE|"+json.dumps(run(),ensure_ascii=False),flush=True)
