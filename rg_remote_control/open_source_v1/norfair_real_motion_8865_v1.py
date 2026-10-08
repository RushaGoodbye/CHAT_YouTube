#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real 886 cigarette motion SHADOW benchmark on actual video frames.

No attempt to certify cigarette identity, no production modification and no
reuse of predicted boxes as ground truth. See status and reason in JSON.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
EVIDENCE=DATA/"release_backups"/"PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648"/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
CURRENT=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
VIDEO=Path(r"\\Desktop-v7gg0en\record\886.mp4")
OUTPUT=DATA/"oss_shadow"/"norfair_886_5_real_motion_v1.json"
FFMPEG=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE")
VERSION="RG_OSS_NORFAIR_REAL_MOTION_SHADOW_V1"
SAMPLE_FPS=12.0
SAMPLE_BEFORE=0.55
SAMPLE_AFTER=0.65

def jread(p):
    if not p.is_file():raise RuntimeError("Required original evidence missing: "+str(p))
    return json.loads(p.read_text(encoding="utf-8-sig"))
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def assert_valid_evidence():
    raw=jread(EVIDENCE);cur=jread(CURRENT);qa=jread(QA)
    r=raw.get("rejected_tracks") or []
    if raw.get("status")!="AMBIGUOUS" or int(raw.get("raw_detection_count") or 0)!=2:
        raise RuntimeError("Unexpected archived evidence schema")
    if len(r)!=1 or len(r[0].get("hits") or [])!=2:
        raise RuntimeError("Saved raw evidence must contain exactly two hits on one original candidate")
    if cur.get("original_detection_report_sha256")!=sha(EVIDENCE):
        raise RuntimeError("Current 886_5 repair does not match archived raw evidence")
    if cur.get("status")!="TRACKED" or cur.get("passed") is not True:
        raise RuntimeError("Existing 886_5 cigarette track no longer valid")
    if qa.get("passed") is not True or (qa.get("coverage_qa") or {}).get("passed") is not True:
        raise RuntimeError("Existing 886_5 cigarette blur coverage no longer valid")
    hits=sorted(r[0]["hits"],key=lambda h:float(h["t"]))
    for h in hits:
        box=h.get("bbox") or []
        if len(box)!=4 or not all(math.isfinite(float(x)) for x in box):
            raise RuntimeError("Invalid archived bounding box")
        x0,y0,x1,y1=map(float,box)
        if not (0<=x0<x1<=1920 and 0<=y0<y1<=1080):
            raise RuntimeError("Archived bounding box outside source video")
    if [str(h.get("class")) for h in hits]!=["smoking cigarette","smoking cigarette"]:
        raise RuntimeError("Unexpected archived detection label")
    times=[float(h["t"]) for h in hits]
    if not (0.05<=times[1]-times[0]<0.10):
        raise RuntimeError("Unexpected original detection time gap")
    return hits

def decode_clip(ffmpeg,video,frames_dir,begin,duration):
    # No audio, no video re-encode to user deliverables: temporary decoded JPEGs only.
    cmd=[str(ffmpeg),"-nostdin","-hide_banner","-loglevel","error",
        "-ss",f"{begin:.5f}","-i",str(video),
        "-t",f"{duration:.5f}","-an","-sn",
        "-vf",f"fps={SAMPLE_FPS:g}","-frames:v","25",
        "-q:v","3","-y",str(frames_dir/"frame_%04d.jpg")]
    proc=subprocess.run(cmd,cwd=str(frames_dir),capture_output=True,
                        text=True,encoding="utf-8",errors="replace",
                        timeout=150,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if proc.returncode:
        raise RuntimeError("FFmpeg frame sampling failed: "+proc.stderr[-1600:])
    paths=sorted(frames_dir.glob("frame_*.jpg"))
    if not (8<=len(paths)<=25):
        raise RuntimeError(f"Insufficient decoded frames: {len(paths)}")
    return paths

def clamp_bbox(bbox,w,h,margin=6):
    x0,y0,x1,y1=[int(round(float(v))) for v in bbox]
    return (max(0,x0-margin),max(0,y0-margin),
            min(w,x1+margin),min(h,y1+margin))

def match_track(frames,seed_box,anchor):
    import cv2
    import numpy as np
    gray=[cv2.cvtColor(f,cv2.COLOR_BGR2GRAY) for f in frames]
    H,W=gray[0].shape
    box=clamp_bbox(seed_box,W,H,margin=7)
    x0,y0,x1,y1=box
    template=gray[anchor][y0:y1,x0:x1]
    if template.size<30 or template.shape[0]<5 or template.shape[1]<5:
        raise RuntimeError("Seed patch too small for meaningful template matching")
    # Constant/unstructured patches are ineligible for positive tracking claims.
    textured=float(template.std())>=7.0
    wh=(x1-x0,y1-y0)
    centers=[None]*len(gray)
    confidences=[None]*len(gray)
    centers[anchor]=[(x0+x1)/2,(y0+y1)/2]
    confidences[anchor]=1.0
    for direction in (1,-1):
        center=list(centers[anchor])
        for i in range(anchor+direction,len(gray) if direction>0 else -1,direction):
            radius=45
            sx=max(0,int(round(center[0]-wh[0]/2-radius)))
            sy=max(0,int(round(center[1]-wh[1]/2-radius)))
            ex=min(W,int(round(center[0]+wh[0]/2+radius)))
            ey=min(H,int(round(center[1]+wh[1]/2+radius)))
            search=gray[i][sy:ey,sx:ex]
            if search.shape[0]<template.shape[0] or search.shape[1]<template.shape[1]:
                break
            method=cv2.TM_CCOEFF_NORMED if textured else cv2.TM_SQDIFF_NORMED
            response=cv2.matchTemplate(search,template,method)
            mn,mx,mnp,mxp=cv2.minMaxLoc(response)
            score=float(mx) if textured else 1.0-float(mn)
            top=(mxp if textured else mnp)
            c=[sx+top[0]+wh[0]/2,sy+top[1]+wh[1]/2]
            if not math.isfinite(score) or score<0.65 or math.dist(c,center)>65:
                break
            centers[i]=[round(v,2) for v in c]
            confidences[i]=round(score,4)
            center=c
    return {
       "template_std":round(float(template.std()),3),
       "template_textured":textured,
       "centers":centers,
       "scores":confidences,
       "frame_count":len(gray),
       "matched_frames":sum(c is not None for c in centers),
       "frame_size":[W,H],
       "seed_bbox":list(seed_box),
    }

def norfair_probe(track):
    import numpy as np
    from norfair import Detection,Tracker
    from importlib.metadata import version
    if version("norfair")!="2.3.0":
        raise RuntimeError("Norfair shadow environment version changed")
    tracker=Tracker(distance_function="euclidean",distance_threshold=120.0,
                    hit_counter_max=6,initialization_delay=1)
    seen=[]
    confirmed=set()
    for i,center in enumerate(track["centers"]):
        if center is not None:
            score=track["scores"][i]
            det=Detection(points=np.asarray([center],dtype=np.float32),
                          scores=np.asarray([max(0.0,min(1.0,float(score)))],dtype=np.float32))
            active=tracker.update(detections=[det])
        else:
            active=tracker.update(detections=[])
        ids=[int(x.id) for x in active if x.id is not None]
        confirmed.update(ids)
        seen.append({"frame":i,"bbox_estimate_available":center is not None,
                     "norfair_returned_ids":ids})
    return {"distinct_confirmed_track_ids":len(confirmed),
            "one_id_continuity":len(confirmed)==1,
            "observations":seen,
            "warning":"Norfair tracks the template-matching estimates, not independent cigarette detections"}

def bench(hits):
    try:
        import cv2
        from importlib.metadata import version
    except ImportError as exc:
        raise RuntimeError("Run only inside isolated Norfair+OpenCV shadow environment") from exc
    if version("opencv-python")!="4.11.0.86":
        raise RuntimeError("OpenCV shadow version differs from validated pin")
    if not FFMPEG.is_file():raise RuntimeError("Known FFmpeg binary missing")
    if not VIDEO.is_file():raise RuntimeError("Original stream video unavailable")
    t0=float(hits[0]["t"])
    start=max(0.0,t0-SAMPLE_BEFORE)
    end=float(hits[1]["t"])+SAMPLE_AFTER
    # no destructive processing, no production file writes
    tmp_root=DATA/"oss_shadow"/"tmp"
    tmp_root.mkdir(parents=True,exist_ok=True)
    print(f"RGMOTION|decode|{start:.3f}-{end:.3f}|fps={SAMPLE_FPS:g}",flush=True)
    with tempfile.TemporaryDirectory(prefix="886_5_motion_",dir=str(tmp_root)) as td:
        folder=Path(td)
        paths=decode_clip(FFMPEG,VIDEO,folder,start,end-start)
        frames=[cv2.imread(str(p)) for p in paths]
        if any(f is None for f in frames):
            raise RuntimeError("Decoded JPEG frame unreadable")
        if any(f.shape!=frames[0].shape for f in frames):
            raise RuntimeError("Inconsistent frame geometry")
        # Approximate alignment only (fps filter pts can move by <= one frame).
        anchor=int(round((t0-start)*SAMPLE_FPS))
        anchor=min(max(anchor,0),len(frames)-1)
        tr=match_track(frames,hits[0]["bbox"],anchor)
    tracked=[c for c in tr["centers"] if c is not None]
    gaps=tr["frame_count"]-tr["matched_frames"]
    nor=norfair_probe(tr)
    displacement=max([math.dist(c,tracked[0]) for c in tracked] or [0])
    # A tiny apparent motion and texture matching alone do not certify the cigarette.
    diagnostic={
       "status":"REAL_FRAMES_ANALYZED",
       "source_video":str(VIDEO),
       "video_read_only":True,
       "source_audio_read_only":True,
       "frames_ocr":False,
       "source_window_sec":{"start":start,"end":end,"duration":round(end-start,5)},
       "frame_rate_sampled":SAMPLE_FPS,
       "alignment_note":"Timecode-to-frame correspondence approximate within about one sample",
       "frame_probe":{k:v for k,v in tr.items() if k not in {"centers","scores"}},
       "candidate_template_track":{
           "matched_frames":tr["matched_frames"],
           "unmatched_frames":gaps,
           "max_displacement_px":round(displacement,3),
           "centers":tr["centers"],
           "normalized_scores":tr["scores"],
       },
       "norfair_observations":nor,
       "model_detected_each_frame":False,
       "confirmed_cigarette_each_frame":False,
       "production_approval":"NOT_GRANTED",
       "recommended_next_test":"SAM2 independently prompted masks with full-frame GT review",
    }
    return diagnostic

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=OUTPUT)
    args=p.parse_args(argv)
    out=args.output.resolve()
    allowed=(DATA/"oss_shadow").resolve()
    if out.suffix.lower()!=".json" or allowed not in out.parents:
        raise RuntimeError("Refusing any output outside F: isolated OSS shadow")
    hits=assert_valid_evidence()
    print("RGMOTION|saved_evidence|PASS",flush=True)
    result=bench(hits)
    payload={"schema":VERSION,"contour":"auto_edit",
      "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "norfair":"2.3.0","opencv":"4.11.0.86",
      "baseline_886_5_detections":2,
      "summary":result,
      "production_modified":False,
      "premiere_xml_modified":False,
      "audio_modified":False,
      "blur_modified":False,
      "stream_reprocessed":False,
      "decision":"SHADOW_ONLY_NO_AUTOMATIC_BLUR_CLEARANCE"}
    out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_name(f".{out.stem}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(temp,out)
    finally:
        if temp.is_file():temp.unlink()
    summary=result["candidate_template_track"]
    print("=== RG NORFAIR 886_5 REAL MOTION RESULT ===",flush=True)
    print(json.dumps({
      "status":result["status"],"sampled_frames":result["frame_probe"]["frame_count"],
      "matched_candidate_frames":summary["matched_frames"],
      "unmatched_frames":summary["unmatched_frames"],
      "max_estimated_motion_px":summary["max_displacement_px"],
      "norfair_one_id_continuity":result["norfair_observations"]["one_id_continuity"],
      "confirmed_cigarette_each_frame":False,
      "production_modified":False,
      "output":str(out),
      "next":"Video mask benchmark (SAM 2) after CUDA/Windows preflight"},
      ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("=== RG NORFAIR 886_5 REAL MOTION STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),
          "production_modified":False},ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
