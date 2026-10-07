#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLOWorld
from rg_ffmpeg_gpu import iter_sampled_frames

VERSION = "RG_CIGARETTE_DETECTOR_WORKER_V1"

def _merge_ranges(rows, gap=0.35):
    vals=[]
    for r in rows or []:
        try:
            a=float(r.get("source_start_sec",r.get("start")))
            b=float(r.get("source_end_sec",r.get("end")))
        except Exception:
            continue
        if b>a:
            vals.append([a,b])
    vals.sort(); out=[]
    for a,b in vals:
        if not out or a>out[-1][1]+gap:
            out.append([a,b])
        else:
            out[-1][1]=max(out[-1][1],b)
    return out

def _iou(a,b):
    ax0,ay0,ax1,ay1=map(float,a); bx0,by0,bx1,by1=map(float,b)
    ix0=max(ax0,bx0);iy0=max(ay0,by0);ix1=min(ax1,bx1);iy1=min(ay1,by1)
    iw=max(0.0,ix1-ix0);ih=max(0.0,iy1-iy0);inter=iw*ih
    aa=max(0.0,ax1-ax0)*max(0.0,ay1-ay0);bb=max(0.0,bx1-bx0)*max(0.0,by1-by0)
    return inter/max(1e-9,aa+bb-inter)

def _nms(rows, threshold=0.48):
    rows=sorted(rows,key=lambda x:float(x.get("score",0)),reverse=True)
    kept=[]
    for r in rows:
        if any(_iou(r["bbox"],k["bbox"])>=threshold for k in kept):
            continue
        kept.append(r)
    return kept

def _predict(model, frame, opts):
    if frame is None or getattr(frame,"size",0)==0:
        return []
    conf=float(opts.get("confidence",0.08))
    iou=float(opts.get("nms_iou",0.5))
    imgsz=int(opts.get("imgsz",1280))
    max_det=int(opts.get("max_detections_per_frame",8))
    result=model.predict(source=frame,conf=conf,iou=iou,imgsz=imgsz,
                         device=0 if torch.cuda.is_available() else "cpu",
                         verbose=False,max_det=max_det)[0]
    out=[]
    boxes=getattr(result,"boxes",None)
    if boxes is None:
        return out
    names=getattr(result,"names",{}) or {}
    H,W=frame.shape[:2]
    for b in boxes:
        try:
            xy=b.xyxy[0].detach().cpu().tolist()
            score=float(b.conf[0].detach().cpu())
            cls=int(b.cls[0].detach().cpu())
            label=str(names.get(cls,cls))
            x0,y0,x1,y1=[int(round(v)) for v in xy]
            if x1<=x0 or y1<=y0:
                continue
            frac=((x1-x0)*(y1-y0))/max(1.0,float(W*H))
            if frac>float(opts.get("max_box_area_fraction",0.055)):
                continue
            out.append({"bbox":[x0,y0,x1,y1],"score":score,"class":label})
        except Exception:
            continue
    return _nms(out,float(opts.get("dedupe_iou",0.45)))

def _scan(model, video, ranges, sample_fps, opts, phase):
    frames=[]; backends=set()
    total=sum(max(0.0,b-a) for a,b in ranges); done=0.0
    for a,b in ranges:
        dur=b-a; count=0
        iterator=iter_sampled_frames(video,a,b,sample_fps=sample_fps,
                                     width=1920,height=1080,
                                     requested=str(opts.get("video_decode_device","auto")),
                                     scale_output=False)
        for t,frame,backend in iterator:
            backends.add(str(backend)); count+=1
            frames.append({"t":round(float(t),5),"boxes":_predict(model,frame,opts)})
            if count%max(1,int(sample_fps))==0:
                frac=(done+min(dur,max(0.0,float(t)-a)))/max(1e-6,total)
                print(f"RGCIGPROGRESS|{min(1.0,frac):.5f}|{phase}",flush=True)
        done+=dur
    return frames,sorted(backends)

def _windows_from_hits(frames, ranges, margin):
    hits=[float(f["t"]) for f in frames if f.get("boxes")]
    if not hits:
        return []
    vals=[]
    for t in hits:
        for a,b in ranges:
            if a-1e-6<=t<=b+1e-6:
                vals.append([max(a,t-margin),min(b,t+margin)])
                break
    vals.sort(); out=[]
    for a,b in vals:
        if not out or a>out[-1][1]+0.12:
            out.append([a,b])
        else:
            out[-1][1]=max(out[-1][1],b)
    return out

def main(inp,outp):
    p=json.loads(Path(inp).read_text(encoding="utf-8"))
    video=Path(p["video"])
    opts=p.get("opts") or {}
    model_path=Path(p["model"])
    classes=list(opts.get("classes") or [
        "cigarette","lit cigarette","cigarette in hand","smoking cigarette"
    ])
    if not video.is_file():
        raise RuntimeError("Video missing: "+str(video))
    if not model_path.is_file():
        raise RuntimeError("Model missing: "+str(model_path))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required for mandatory cigarette detector")
    ranges=_merge_ranges(p.get("ranges") or [],
                         gap=float(opts.get("range_merge_gap_sec",0.35)))
    model=YOLOWorld(str(model_path))
    model.set_classes(classes)
    coarse_fps=max(1.0,float(opts.get("coarse_fps",3.0)))
    refine_fps=max(coarse_fps,float(opts.get("refine_fps",12.0)))
    coarse,be1=_scan(model,video,ranges,coarse_fps,opts,"coarse")
    refine_windows=_windows_from_hits(
        coarse,ranges,float(opts.get("refine_margin_sec",1.1)))
    refine=[];be2=[]
    if refine_windows:
        refine,be2=_scan(model,video,refine_windows,refine_fps,opts,"refine")
    all_frames={}
    for fr in coarse:
        if fr.get("boxes"):
            all_frames[round(float(fr["t"]),4)]=fr
    for fr in refine:
        all_frames[round(float(fr["t"]),4)]=fr
    rows=[all_frames[k] for k in sorted(all_frames)]
    raw=sum(len(x.get("boxes") or []) for x in rows)
    out={
        "version":VERSION,"passed":True,"video":str(video),"model":str(model_path),
        "classes":classes,"cuda":True,"device":torch.cuda.get_device_name(0),
        "source_ranges":ranges,"coarse_fps":coarse_fps,"refine_fps":refine_fps,
        "refine_windows":refine_windows,"frames":rows,
        "raw_detection_count":raw,
        "video_decode_backends":sorted(set(be1+be2)),
    }
    Path(outp).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RGCIGDETECT|"+json.dumps(
        {"passed":True,"raw":raw,"frames":len(rows)},ensure_ascii=False),flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    main(a.input,a.output)
