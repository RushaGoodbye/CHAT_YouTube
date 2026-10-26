#!/usr/bin/env python3
"""Real visual + guest identity comparison for stream 907 (read-only).

No media/XML/queue writes, no threshold relaxation, no automatic trim.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
WINDOWS={
    "clock_grid":(4775.,4855.),
    "local_visual":(4895.,4985.),
}
FPS=0.34

def compact(frames, ref, classifier):
    states={"CURRENT":0,"OTHER_FACE":0,"PLACEHOLDER":0,"UNKNOWN":0}
    high=[]
    checked=0
    for t,frame in frames:
        state,sims,score,nfaces,other=classifier(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
        checked+=1
        states[state if state in states else "UNKNOWN"]+=1
        if state=="CURRENT":
            high.append({"time":round(float(t),2),"score":round(float(score),3)})
    return {"frames_checked":checked,"states":states,"current_examples":high[:10],
            "current_peak":max((x["score"] for x in high),default=0)}

def summarize(data):
    rows={}
    for label,entry in data.items():
        rows[label]={"current_hits":entry.get("states",{}).get("CURRENT",0),
                     "checked":entry.get("frames_checked",0),
                     "current_peak":entry.get("current_peak",0)}
    return rows

def run():
    sys.path.insert(0,str(APP))
    import cv2
    from rg_server_resolver import resolve_video
    from rg_clock_selector import _iter_window_ffmpeg
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    from rg_face_identity import models_ready
    video,*_=resolve_video(r"\\Desktop-v7gg0en\record","907")
    if not video or not Path(video).is_file():
        raise RuntimeError("Original 907 video not found; no changes")
    report={"schema":"RG_907_VISUAL_ANCHOR_EVIDENCE_V1","stream":"907",
            "read_only":True,"media_writes":0,"xml_writes":0,"queue_writes":0,
            "models_ready":bool(models_ready()),"shots":{}}
    for i in (1,2):
        path=SCREEN/f"907-{i}.jpg"
        result={"screenshot":path.name,"present":path.is_file()}
        if not path.is_file():
            report["shots"][str(i)]=result
            continue
        img=cv2.imread(str(path))
        if img is None:
            result["error"]="IMAGE_UNREADABLE"
            report["shots"][str(i)]=result
            continue
        ref,meta=_reference_guest_descriptor(img)
        result["reference"]={k:v for k,v in meta.items() if k!="embedding"}
        if ref is not None:
            scans={}
            for label,(a,b) in WINDOWS.items():
                iterator=_iter_window_ffmpeg(str(video),a,b,sample_fps=FPS)
                scans[label]=compact(iterator,ref,_frame_identity_state)
            result["windows"]=summarize(scans)
            result["evidence"]={
                "clock_grid_guest_present":scans["clock_grid"]["states"]["CURRENT"]>=3,
                "visual_guest_present":scans["local_visual"]["states"]["CURRENT"]>=3,
                "identity_ambiguous":(scans["clock_grid"]["states"]["CURRENT"]>=3 and
                                      scans["local_visual"]["states"]["CURRENT"]>=3)}
        report["shots"][str(i)]=result
    return report

if __name__=="__main__":
    print("RG_907_ANCHOR_EVIDENCE|"+json.dumps(run(),ensure_ascii=False),flush=True)
