#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated TRUE cigarette positive example extraction at stream 892 01:58:41.

Read-only source. Saves 24 second video-only review clip, 4fps contact sheets,
9 full-resolution JPEGs near timecode, and a single ZIP. No image classifier
or semantic label is run. This does not update RG Auto Edit Studio, Premiere,
the stream, the 886_5 quarantine, or any original audio.

Run --self-test first. Only use with user-authorized 892.mp4 source.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

VERSION="RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1"
SOURCE_DEFAULT=Path(r"\\Desktop-v7gg0en\record\892.mp4")
FFMPEG_DEFAULT=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE")
OUT_DEFAULT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\positive_892_015841_v1")
TIMECODE="01:58:41"
ANCHOR_SEC=7121.0
START_SEC=7109.0
DURATION_SEC=24.0
END_SEC=START_SEC+DURATION_SEC
FPS=4
FRAME_CAP=100
CONTACT_COLUMNS=3
CONTACT_ROWS=3
CONTACT_CELL_W=640
CONTACT_CELL_H=385
VIDEO_NAME="892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
ZIP_NAME="RG_892_CIGARETTE_GOLD_015841.zip"

def checksum(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def validate_source(video, ffmpeg, out):
    if not video.is_file():
        raise RuntimeError("892 original source video not found: "+str(video))
    if video.name.lower()!="892.mp4":
        raise RuntimeError("Expected user-authorized original 892.mp4, got "+video.name)
    if not ffmpeg.is_file():
        raise RuntimeError("Expected known FFmpeg executable missing: "+str(ffmpeg))
    if not (out.drive.lower()=="f:" and "oss_shadow" in out.parts):
        raise RuntimeError("Outputs must remain in isolated F: OSS shadow folder")
    parent=out.parent
    if not parent.is_dir():
        raise RuntimeError("F: OSS shadow parent directory missing")
    if not video.stat().st_size>1024*1024:
        raise RuntimeError("Original 892.mp4 unexpectedly small")
    return {"size":video.stat().st_size,"mtime_ns":video.stat().st_mtime_ns}

def run_ffmpeg(exe,cmd,timeout):
    command=[str(exe),"-nostdin","-hide_banner","-loglevel","error"]+list(cmd)
    proc=subprocess.run(command,capture_output=True,text=True,
        encoding="utf-8",errors="replace",timeout=timeout,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if proc.returncode:
        raise RuntimeError("FFmpeg failed: "+(proc.stderr or "")[-1200:])
    return True

def make_tile(image,idx,source_sec):
    import cv2
    import numpy as np
    if image is None or len(image.shape)!=3 or image.shape[1]<900 or image.shape[0]<500:
        raise RuntimeError("Sampled 892 source frame has invalid resolution")
    tile=np.full((CONTACT_CELL_H,CONTACT_CELL_W,3),22,dtype=np.uint8)
    tile[:360,:]=cv2.resize(image,(CONTACT_CELL_W,360),interpolation=cv2.INTER_AREA)
    text=f"892 / SOURCE ~{source_sec:.2f}s / CANDIDATE NOT VERIFIED"
    cv2.putText(tile,text,(7,378),cv2.FONT_HERSHEY_SIMPLEX,0.44,
                (235,235,235),1,cv2.LINE_AA)
    return tile

def make_sheets(images,output,center_folder):
    import cv2
    import numpy as np
    canvas=np.full((CONTACT_ROWS*CONTACT_CELL_H,
                    CONTACT_COLUMNS*CONTACT_CELL_W,3),22,dtype=np.uint8)
    outputs=[]
    samples=[]
    keyframes=[]
    # fps=4 samples are spaced about 250ms. Actual timestamps are
    # approximate until validated with frame-accurate metadata.
    selected=[i for i in range(len(images)) if abs(START_SEC+i/FPS-ANCHOR_SEC)<=1.0]
    if not selected:
        raise RuntimeError("Target timecode not covered by decoded frames")
    center_folder.mkdir(parents=True,exist_ok=False)
    for idx,src in enumerate(images):
        image=cv2.imread(str(src),cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Cannot open sampled 892 frame "+str(src))
        seconds=START_SEC+idx/FPS
        r=(idx%(CONTACT_ROWS*CONTACT_COLUMNS))//CONTACT_COLUMNS
        c=idx%CONTACT_COLUMNS
        y0=r*CONTACT_CELL_H;x0=c*CONTACT_CELL_W
        canvas[y0:y0+CONTACT_CELL_H,x0:x0+CONTACT_CELL_W]=make_tile(image,idx,seconds)
        if idx in selected:
            p=center_folder/f"892_CIGARETTE_POTENTIAL_{idx+1:03d}.jpg"
            if not cv2.imwrite(str(p),image,[cv2.IMWRITE_JPEG_QUALITY,94]):
                raise RuntimeError("Cannot preserve original resolution selected JPEG")
            keyframes.append({"file":p.name,"source_time_approx_sec":round(seconds,2)})
        samples.append({"source_time_approx_sec":round(seconds,2),"source_frame_index":idx})
        if (idx+1)%(CONTACT_ROWS*CONTACT_COLUMNS)==0 or idx==len(images)-1:
            p=output/f"892_015841_CONTACT_{len(outputs)+1:02d}.jpg"
            if not cv2.imwrite(str(p),canvas,[cv2.IMWRITE_JPEG_QUALITY,90]):
                raise RuntimeError("Cannot write 892 review sheet")
            outputs.append(p)
            canvas[:]=22
    return outputs,keyframes,samples

def process(src,ffmpeg,out):
    orig=validate_source(src,ffmpeg,out)
    if out.exists():
        manifest=out/"manifest.json"
        archive=out/ZIP_NAME
        if manifest.is_file() and archive.is_file():
            previous=json.loads(manifest.read_text(encoding="utf-8"))
            if (previous.get("schema")==VERSION and
                previous.get("stream")=="892" and
                previous.get("original_timecode")==TIMECODE and
                previous.get("original_media_mtime_ns")==orig["mtime_ns"] and
                previous.get("original_media_size_bytes")==orig["size"] and
                previous.get("archive_sha256")==checksum(archive)):
                print("=== RG 892 VERIFIED POSITIVE REVIEW ARCHIVE ALREADY READY ===",flush=True)
                emit(previous,archive)
                return
        raise RuntimeError("Output folder exists but is not a verified reusable capture; no overwrite: "+str(out))
    staging=Path(tempfile.mkdtemp(prefix=".892_cigarette_capture_",dir=str(out.parent)))
    try:
        frame_dir=staging/"sample_tmp"
        frame_dir.mkdir()
        keydir=staging/"keyframes"
        sheetdir=staging/"contact_sheets"
        sheetdir.mkdir()
        mp4=staging/VIDEO_NAME
        print("RG892|VIDEO_ONLY_CLIP|source=01:58:29..01:58:53",flush=True)
        run_ffmpeg(ffmpeg,[
             "-ss",f"{START_SEC:.3f}","-i",str(src),
             "-t",f"{DURATION_SEC:.3f}","-map","0:v:0",
             "-an","-sn","-dn",
             "-c:v","libx264","-preset","veryfast","-crf","21",
             "-pix_fmt","yuv420p","-movflags","+faststart",
             "-y",str(mp4)
        ],timeout=420)
        if not mp4.is_file() or mp4.stat().st_size<25000:
            raise RuntimeError("Review MP4 missing or unexpectedly small")
        # Validate review clip decodes, without audio access.
        import cv2
        cap=cv2.VideoCapture(str(mp4))
        ok,first=cap.read()
        cap.release()
        if not ok or first is None or first.shape[1]<900:
            raise RuntimeError("Review MP4 is not readable at full resolution")
        print("RG892|CONTACT_SAMPLING|4fps|window=24s",flush=True)
        run_ffmpeg(ffmpeg,[
            "-ss",f"{START_SEC:.3f}","-i",str(src),
            "-t",f"{DURATION_SEC:.3f}","-map","0:v:0",
            "-an","-sn","-dn",
            "-vf",f"fps={FPS}",
            "-frames:v",str(FRAME_CAP),
            "-q:v","3","-y",str(frame_dir/"source_%04d.jpg")
        ],timeout=420)
        frames=sorted(frame_dir.glob("source_*.jpg"))
        if not 75<=len(frames)<=100:
            raise RuntimeError(f"Expected ~96 sampled frames, got {len(frames)}")
        sheets,keys,samples=make_sheets(frames,sheetdir,keydir)
        if len(keys)<7:
            raise RuntimeError("Insufficient target high-resolution frames")
        note={
           "schema":VERSION,"created_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
           "contour":"auto_edit","stream":"892",
           "original_timecode":TIMECODE,"source_center_sec":ANCHOR_SEC,
           "source_start_sec":START_SEC,"source_end_sec":END_SEC,
           "window_duration_sec":DURATION_SEC,"source_path":str(src),
           "original_media_size_bytes":orig["size"],
           "original_media_mtime_ns":orig["mtime_ns"],
           "sample_fps":FPS,
           "sampled_frame_count":len(frames),
           "contact_sheet_count":len(sheets),
           "keyframe_count":len(keys),
           "keyframes":keys,
           "timestamps":"Approximate ffmpeg fps sampling. Do not treat screenshot time stamps as frame-exact ground truth.",
           "video_clip":VIDEO_NAME,
           "video_clip_no_audio":True,
           "positive_visual_label":"USER_CANDIDATE_PENDING_REVIEW",
           "cigarette_semantically_confirmed":False,
           "model_inference_run":False,
           "frame_perfect_tracking_verified":False,
           "full_892_stream_scanned":False,
           "original_video_modified":False,"original_audio_modified":False,
           "premiere_xml_modified":False,"studio_modified":False,
           "quarantine_886_5_modified":False,
           "release_allowed":False,
           "limitations":"24-second real positive candidate for visual labeling only; no independent detector or production blur validated.",
           "review_archive":ZIP_NAME,
        }
        (staging/"manifest.json").write_text(json.dumps(note,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        archive=staging/ZIP_NAME
        with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            z.write(mp4,VIDEO_NAME)
            z.write(staging/"manifest.json","manifest.json")
            for sheet in sheets:
                z.write(sheet,"contact_sheets/"+sheet.name)
            for k in keys:
                z.write(keydir/k["file"],"keyframes/"+k["file"])
        # Avoid self-referential archive checksum inside the ZIP.
        note["archive_sha256"]=checksum(archive)
        note["archive_size_mb"]=round(archive.stat().st_size/1024**2,2)
        (staging/"manifest.json").write_text(json.dumps(note,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        shutil.rmtree(frame_dir)
        # Create final output atomically at directory level where possible.
        os.rename(staging,out)
        emit(note,out/ZIP_NAME)
    finally:
        if staging.exists():shutil.rmtree(staging,ignore_errors=True)

def emit(note,archive):
    print("=== RG 892 REAL CIGARETTE POSITIVE REVIEW PACK COMPLETE ===",flush=True)
    print(json.dumps({
      "status":"VISUAL_LABEL_REVIEW_READY",
      "stream":note["stream"],
      "timecode":note["original_timecode"],
      "source_window":"01:58:29 - 01:58:53",
      "video_only_duration_sec":note["window_duration_sec"],
      "frames_sampled":note["sampled_frame_count"],
      "contact_sheets":note["contact_sheet_count"],
      "keyframes_full_resolution":note["keyframe_count"],
      "archive":str(archive),
      "archive_size_mb":note["archive_size_mb"],
      "production_modified":False,
      "original_audio_modified":False,
      "886_5_quarantine_unchanged":True,
      "semantic_positive_confirmed":False
    },ensure_ascii=False,indent=2),flush=True)

def self_test():
    assert ANCHOR_SEC==1*3600+58*60+41
    assert START_SEC==ANCHOR_SEC-12 and END_SEC==ANCHOR_SEC+12
    assert FPS==4 and FRAME_CAP>=DURATION_SEC*FPS
    import numpy as np
    frame=np.zeros((1080,1920,3),dtype=np.uint8)
    tile=make_tile(frame,0,ANCHOR_SEC)
    assert tile.shape==(385,640,3)
    assert tile.dtype==np.uint8
    assert len([i for i in range(96) if abs(START_SEC+i/FPS-ANCHOR_SEC)<=1.0])==9
    assert VERSION and ZIP_NAME.endswith(".zip") and "NO_AUDIO" in VIDEO_NAME
    print("RG_892_POSITIVE_REAL_VIDEO_CAPTURE_PREWRITE_SELFTEST: PASS",flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--source",type=Path,default=SOURCE_DEFAULT)
    ap.add_argument("--ffmpeg",type=Path,default=FFMPEG_DEFAULT)
    ap.add_argument("--out",type=Path,default=OUT_DEFAULT)
    args=ap.parse_args()
    if args.self_test:
        self_test()
        return
    process(args.source,args.ffmpeg,args.out)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG 892 REAL POSITIVE FRAME CAPTURE STOPPED ===",flush=True)
        print(json.dumps({
          "status":"STOPPED","reason":str(exc),"production_modified":False,
          "quarantine_886_5_modified":False
        },ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
