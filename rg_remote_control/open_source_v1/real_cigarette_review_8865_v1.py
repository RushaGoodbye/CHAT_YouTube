#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""886_5 read-only visual ground-truth review pack. Does NOT detect cigarettes.

Builds contact sheets using original RGB video frames and fixed ROIs anchored
at previously saved two cigarette detections. Source & Premiere unchanged.
Sheet text says REVIEW REQUIRED, NEVER a validated track or final blur.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np

from norfair_real_motion_8865_v1 import (
    assert_valid_evidence, DATA, VIDEO, FFMPEG, sha,
)
EVIDENCE=DATA/"release_backups"/"PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648"/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
ROOT=DATA/"oss_shadow"
OUTPUT=ROOT/"review_886_5"
SCHEMA="RG_CIGARETTE_8865_REAL_GROUND_TRUTH_REVIEW_V1"
FPS=10.0
MAX_FRAMES=24
CELL_W=900
CELL_H=315
COLS=2
ROWS=3

def sample_video(start,duration,destination):
    pattern=destination/"frame_%04d.png"
    cmd=[str(FFMPEG),"-nostdin","-hide_banner","-loglevel","error",
         "-ss",f"{start:.5f}","-i",str(VIDEO),
         "-t",f"{duration:.5f}","-an","-sn",
         "-vf",f"fps={FPS:g}","-frames:v",str(MAX_FRAMES),
         "-y",str(pattern)]
    proc=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",
                        errors="replace",timeout=150,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if proc.returncode!=0:
        raise RuntimeError("Read-only video sampling failed: "+proc.stderr[-1200:])
    images=sorted(destination.glob("frame_*.png"))
    if not (20<=len(images)<=MAX_FRAMES):
        raise RuntimeError("Expected 20..24 sampled frames, got "+str(len(images)))
    return images

def make_tile(frame,box,frame_number,absolute_timestamp):
    height,width=frame.shape[:2]
    if width!=1920 or height!=1080:
        raise RuntimeError("Unexpected video frame geometry, refusing coordinate alignment")
    x0,y0,x1,y1=map(float,box)
    cx=int(round((x0+x1)/2));cy=int(round((y0+y1)/2))
    # Crop is fixed around original raw detector hit, not a newly found cigarette.
    left=max(0,cx-130); top=max(0,cy-110)
    right=min(width,cx+130);bottom=min(height,cy+110)
    if right<=left+40 or bottom<=top+40:
        raise RuntimeError("Fixed ROI outside video geometry")
    tile=np.full((CELL_H,CELL_W,3),25,dtype=np.uint8)
    overview=cv2.resize(frame,(552,310),interpolation=cv2.INTER_AREA)
    roi=frame[top:bottom,left:right]
    zoom=cv2.resize(roi,(335,282),interpolation=cv2.INTER_CUBIC)
    # Fixed seed ROI visible on overview ONLY, no dynamic "tracking" is claimed.
    rx0=int(round(left*552/width)); ry0=int(round(top*310/height))
    rx1=int(round(right*552/width));ry1=int(round(bottom*310/height))
    cv2.rectangle(overview,(rx0,ry0),(rx1,ry1),(255,200,30),2)
    tile[5:315,0:552]=overview
    tile[5:287,565:900]=zoom
    cv2.rectangle(tile,(565,5),(899,286),(255,200,30),2)
    label=f"{frame_number:02d}  ~{absolute_timestamp:.2f}s  FIXED ROI / NOT A DETECTION"
    cv2.putText(tile,label,(567,306),cv2.FONT_HERSHEY_SIMPLEX,0.36,
                (255,255,255),1,cv2.LINE_AA)
    return tile

def contact_sheets(frames,box,start,dest):
    sheet_w=CELL_W*COLS
    sheet_h=CELL_H*ROWS
    saved=[]
    for sheet_index in range((len(frames)+COLS*ROWS-1)//(COLS*ROWS)):
        canvas=np.full((sheet_h,sheet_w,3),23,dtype=np.uint8)
        for k in range(COLS*ROWS):
            i=sheet_index*(COLS*ROWS)+k
            if i>=len(frames):break
            im=frames[i]
            tile=make_tile(im,box,i+1,start+i/FPS)
            row,col=divmod(k,COLS)
            canvas[row*CELL_H:(row+1)*CELL_H,
                   col*CELL_W:(col+1)*CELL_W]=tile
        file=dest/f"886_5_REVIEW_{sheet_index+1:02d}.jpg"
        if not cv2.imwrite(str(file),canvas,[cv2.IMWRITE_JPEG_QUALITY,91]):
            raise RuntimeError("Unable to save contact sheet: "+str(file))
        saved.append(file)
    return saved

def hash_file(file):
    digest=hashlib.sha256()
    with file.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-dir",type=Path,default=OUTPUT)
    args=ap.parse_args()
    dest=args.output_dir.resolve()
    root=ROOT.resolve()
    if root not in dest.parents:
        raise RuntimeError("Only F: isolated OSS shadow output allowed")
    if not (VIDEO.is_file() and FFMPEG.is_file()):
        raise RuntimeError("Original video or known FFmpeg binary missing")
    hits=assert_valid_evidence()
    seed=hits[0]["bbox"]
    timestamp=float(hits[0]["t"])
    start=max(0,timestamp-0.65)
    duration=MAX_FRAMES/FPS+0.1
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError("Review output folder already contains data; do not overwrite")
    dest.mkdir(parents=True,exist_ok=True)
    tmp_root=ROOT/"tmp"
    tmp_root.mkdir(parents=True,exist_ok=True)
    print(f"RG_REVIEW|decode|{start:.3f}-{start+duration:.3f}|fps={FPS:g}",flush=True)
    with tempfile.TemporaryDirectory(prefix="rg_8865_review_",dir=str(tmp_root)) as td:
        paths=sample_video(start,duration,Path(td))
        frames=[]
        for path in paths:
            frame=cv2.imread(str(path))
            if frame is None:
                raise RuntimeError("Temporary decoded frame unreadable")
            frames.append(frame)
        sheets=contact_sheets(frames,seed,start,dest)
    report={
      "schema":SCHEMA,
      "created_utc":datetime.now(timezone.utc).isoformat(),
      "status":"VISUAL_REVIEW_READY",
      "stream":"886","dialogue":"886_5",
      "frame_count":len(frames),
      "start_source_time_sec":round(start,5),
      "fps_sampled":FPS,
      "timecode_alignment":"Approximate; FFmpeg fps resampling can shift a frame",
      "fixed_reference_bbox":list(seed),
      "fixed_bbox_semantics":"ARCHIVED_SEED_HINT_ONLY_NOT_GROUND_TRUTH",
      "actual_cigarette_labelled_frames":0,
      "review_required":"Inspect all image tiles; cigarette vs finger/background cannot be inferred from this script",
      "candidate_detections_per_frame":False,
      "production_approved":False,
      "source_video_modified":False,
      "source_audio_modified":False,
      "production_xml_modified":False,
      "mandatory_blur_modified":False,
      "sheets":[{"path":str(p),"sha256":hash_file(p)} for p in sheets],
      "next":"Human-confirmed labels and independent semantic detector comparison; do not automatically enable blur from ROI tracking"
    }
    out=dest/"review_manifest.json"
    temp=dest/"._review_manifest.tmp"
    try:
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(temp,out)
    finally:
        if temp.exists():temp.unlink()
    print("=== RG 886_5 REAL FRAME REVIEW PACK RESULT ===",flush=True)
    print(json.dumps({
       "status":report["status"],
       "frames":len(frames),"sheets":len(sheets),
       "ground_truth_labelled":False,
       "production_modified":False,
       "review_folder":str(dest),
       "manifest":str(out),
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG 886_5 REAL FRAME REVIEW PACK STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),"production_modified":False},ensure_ascii=False),flush=True)
        raise SystemExit(2)
