#!/usr/bin/env python3
"""Diagnose 903 held guests from installed screenshots and original source. Read only.

No downloaded models, no images or embeddings exported, no media/XML/cache edits,
no automatic approval of ambiguous guest identity.
"""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
SCREEN=Path(r"\\Desktop-v7gg0en\record\Screens")
SAMPLES=(("EARLY",3593.5,3730.,0.33),("ANCHOR",3875.,4030.,0.33))

def detections(image,face_finder):
    h,w=image.shape[:2]
    probes=[]
    for name,fraction,threshold in (
        ("UPPER_48",.48,.50),("UPPER_70",.70,.43),
        ("FULL",1.,.40)):
        roi=image[:max(32,int(h*fraction)),:]
        faces=face_finder(roi,score_threshold=threshold,min_face_px=18)
        filtered=[dict(f) for f in faces
                  if float(f.get("area",0))>=max(450.,roi.shape[0]*w*.0009)]
        right=[f for f in filtered if float(f.get("center_x",0))>=w*.58]
        probes.append({"roi":name,"found":len(filtered),"right_guest_candidates":len(right),
                       "right_face_scores":[round(float(x.get("score",0)),3) for x in right[:4]],
                       "right_boxes":[[round(float(q),1) for q in x.get("bbox",[])[:4]]
                                       for x in right[:4]]})
    return probes

def source_path(xml):
    from guest_handoff_shadow_batch_v1 import local_media_path
    root=ET.parse(xml).getroot()
    paths=[local_media_path(x.text or "")
           for x in root.findall(".//sequence/media/video//pathurl")]
    paths=[p for p in paths if p is not None and p.is_file()]
    uniq=list(dict.fromkeys(paths))
    if len(uniq)!=1: raise RuntimeError("Cannot uniquely locate original stream media")
    return uniq[0]

def visual_window(video,ref,window,iterator,classifier):
    tag,start,end,fps=window
    summary={"window":tag,"sampled":0,"current_hits":0,
             "other_hits":0,"placeholder_hits":0,"best_match_sec":None,
             "best_match_score":0.,"current_times_first":[]}
    try:
        for t,frame in iterator(str(video),start,end,sample_fps=fps):
            state,sims,score,nfaces,_=classifier(frame,{"CURRENT":ref},layout_mode="RIGHT_WINDOW")
            summary["sampled"]+=1
            if state=="CURRENT":
                summary["current_hits"]+=1
                if len(summary["current_times_first"])<8:
                    summary["current_times_first"].append(round(float(t),2))
            elif state in ("PLACEHOLDER","UNKNOWN"):
                summary["placeholder_hits"]+=1
            else:
                summary["other_hits"]+=1
            if float(score)>summary["best_match_score"]:
                summary["best_match_score"]=round(float(score),4)
                summary["best_match_sec"]=round(float(t),2)
    except Exception as e:
        summary["scan_error_type"]=type(e).__name__
    return summary

def analyze(app=APP,shots=SCREEN):
    sys.path.insert(0,str(app))
    import cv2
    from rg_face_identity import models_ready,face_candidates_from_image
    from rg_guest_identity_boundary import _reference_guest_descriptor,_frame_identity_state
    from rg_clock_selector import _iter_window_ffmpeg
    report={"schema":"RG_903_GUEST_REFERENCE_EVIDENCE_V1",
            "read_only":True,"media_writes":0,"xml_writes":0,
            "auto_approve_guest":False,"models_ready":bool(models_ready()),
            "screenshots":{}}
    for ix in (2,5):
        path=shots/f"903-{ix}.jpg"
        row={"present":path.is_file()}
        if not path.is_file():
            report["screenshots"][str(ix)]=row
            continue
        image=cv2.imread(str(path))
        if image is None:
            row["error"]="UNREADABLE_IMAGE"
        else:
            row["width"]=int(image.shape[1]);row["height"]=int(image.shape[0])
            row["probes"]=detections(image,face_candidates_from_image)
            ref,meta=_reference_guest_descriptor(image)
            row["standard_reference"]={k:v for k,v in meta.items() if k!="embedding"}
            if ix==2 and ref is not None:
                try:
                    xml=app/"903"/"RG_EDITED_903_1_R3.xml"
                    video=source_path(xml)
                    row["current_vs_source"]=[
                        visual_window(video,ref,w,_iter_window_ffmpeg,_frame_identity_state)
                        for w in SAMPLES]
                except Exception as e:
                    row["source_error_type"]=type(e).__name__
        report["screenshots"][str(ix)]=row
    return report

if __name__=="__main__":
    print("RG_903_REFERENCE_EVIDENCE|"+json.dumps(analyze(),ensure_ascii=False),flush=True)
