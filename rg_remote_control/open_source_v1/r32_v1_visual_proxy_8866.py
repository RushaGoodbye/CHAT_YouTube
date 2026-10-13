#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R32 full-length 886_6 V1 visual proxy, SHADOW-ONLY.

Reconstructs only the BASE V1 footage from the archived FCP7 Premiere XML
and original multi-hour 886.mp4 recording. No Premiere overlays, masks or
audio are in this diagnostic. NEVER publish as an edited dialogue.

All outputs are new files under F: shadow. NEVER modify input source XML,
original stream, other Studio files or the approved R25 candidate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(r"F:\RG_AUTO_EDIT")
APP=ROOT/"RG Auto Edit App"
DATA=ROOT/"RG Auto Edit Data"
XML=APP/"RG_EDITED_886_6.xml"
SOURCE=Path(r"\\Desktop-v7gg0en\record\886.mp4")
FFMPEG=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE")
OUTPUT=DATA/"oss_shadow"/"RG_R32_8866_V1_30FPS"
PREVIEW=OUTPUT/"R32_8866_V1_PROXY_NO_AUDIO_NOT_FOR_RELEASE.mp4"
SCHEMA="RG_R32_V1_VISUAL_PROXY_SHADOW_V1"
FPS=30
LENGTH=5842

def source_rows(xml_bytes):
    root=ET.fromstring(xml_bytes)
    seq=root.find(".//sequence")
    if seq is None: raise ValueError("Missing FCP7 sequence")
    if int(seq.findtext("duration","0"))!=LENGTH or int(seq.findtext("./rate/timebase","0"))!=FPS:
        raise ValueError("Refuse unfamiliar sequence timing")
    tracks=seq.findall("./media/video/track")
    if len(tracks)<1: raise ValueError("No V1")
    spans=[]
    for clip in tracks[0].findall("clipitem"):
        vals=[clip.findtext(k) for k in ("start","end","in","out")]
        if any(v is None for v in vals): continue
        start,end,src_in,src_out=map(int,vals)
        if end<=start or src_out<=src_in or start<0 or end>LENGTH: continue
        spans.append({"start":start,"end":end,"in":src_in,"out":src_out,
                      "duration":end-start,"frame_discrepancy":(src_out-src_in)-(end-start)})
    spans.sort(key=lambda x:(x["start"],x["end"]))
    if not spans: raise ValueError("No valid source clips")
    cursor=0
    for clip in spans:
        if clip["start"]!=cursor:
            raise ValueError(f"V1 hole/overlap at frame {cursor}; next starts {clip['start']}")
        if abs(clip["frame_discrepancy"])>1:
            raise ValueError("Source duration mismatch greater than one frame")
        cursor=clip["end"]
    if cursor!=LENGTH:
        raise ValueError("V1 does not cover end: "+str(cursor))
    return spans

def selftest():
    fake=b'<xmeml><sequence><duration>5842</duration><rate><timebase>30</timebase></rate><media><video><track>'+(
        b'<clipitem><start>0</start><end>3000</end><in>338000</in><out>341000</out></clipitem>'
        b'<clipitem><start>3000</start><end>5842</end><in>341000</in><out>343841</out></clipitem>'
    )+b'</track></video></media></sequence></xmeml>'
    r=source_rows(fake)
    assert len(r)==2 and r[1]["frame_discrepancy"]==-1
    assert sum(x["duration"] for x in r)==5842
    print("RG_R32_SHADOW_TIMELINE_SELFTEST: PASS")

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(2**20),b""):h.update(chunk)
    return h.hexdigest()

def check_media(media):
    import cv2
    cap=cv2.VideoCapture(str(media))
    if not cap.isOpened(): raise RuntimeError("Cannot open generated proxy")
    frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rate=cap.get(cv2.CAP_PROP_FPS)
    samples=[]
    for f in (0,500,1400,2800,4200,5841):
        cap.set(cv2.CAP_PROP_POS_FRAMES,f)
        ok,img=cap.read()
        samples.append({"frame":f,"decoded":bool(ok and img is not None)})
    cap.release()
    return {"frame_count":frames,"width":width,"height":height,"fps":rate,
            "samples":samples,
            "video_geometry_ok":frames==LENGTH and width==960 and height==540
                                and abs(rate-FPS)<0.01 and all(x["decoded"] for x in samples)}

def run_cmd(cmd,timeout):
    return subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,
                          encoding="utf-8",errors="replace",
                          creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest",action="store_true")
    ap.add_argument("--render",action="store_true")
    opts=ap.parse_args()
    if opts.selftest:
        selftest();return
    if not XML.is_file() or not SOURCE.is_file() or not FFMPEG.is_file():
        raise SystemExit("Source XML/video/FFmpeg inaccessible")
    raw=XML.read_bytes()
    spans=source_rows(raw)
    report={
        "schema":SCHEMA,"source_video_read_only":True,"xml_modified":False,
        "studio_modified":False,"audio_in_output":False,
        "clips":len(spans),"timeline_frames":LENGTH,
        "source_delta_plus_one":sum(c["frame_discrepancy"]==1 for c in spans),
        "source_delta_minus_one":sum(c["frame_discrepancy"]==-1 for c in spans),
        "xml_sha256":hashlib.sha256(raw).hexdigest(),
        "complete_v1_coverage":True,
        "version":"R32 shadow, NOT a Premiere render",
        "release_ready":False,
    }
    print("RG_R32_PREFLIGHT="+json.dumps(report,sort_keys=True),flush=True)
    if not opts.render: return
    if OUTPUT.exists():
        # Never overwrite a previous video or partial shadow run.
        raise SystemExit("R32 shadow folder already exists; not overwriting")
    OUTPUT.mkdir(parents=True,exist_ok=False)
    segments=OUTPUT/"segments"
    segments.mkdir(exist_ok=False)
    if not SOURCE.stat().st_size==15333867413:
        raise SystemExit("Original 886.mp4 size changed: STOP")
    paths=[]
    for n,c in enumerate(spans):
        dst=segments/(f"v1_{n:03d}.mp4")
        paths.append(dst)
        # Accurate seek is used because we TRANSCODE, not -c copy.
        cmd=[str(FFMPEG),"-nostdin","-hide_banner","-loglevel","error",
             "-ss",f"{c['in']/FPS:.6f}","-i",str(SOURCE),
             "-an","-sn","-dn","-vf","fps=30,scale=960:540:flags=bicubic",
             "-frames:v",str(c["duration"]),
             "-c:v","libx264","-preset","ultrafast","-crf","25",
             "-pix_fmt","yuv420p","-threads","3","-y",str(dst)]
        p=run_cmd(cmd,timeout=180)
        if p.returncode or not dst.is_file() or dst.stat().st_size==0:
            raise RuntimeError(f"Segment {n}/{len(spans)} failed: {p.stderr[-700:]}")
        if n%10==0 or n==len(spans)-1:
            print(f"RG_R32_RENDER_PROGRESS={n+1}/{len(spans)}",flush=True)
    listing=OUTPUT/"concat.txt"
    listing.write_text("".join("file '"+p.as_posix().replace("'","'\\''")+"'\n"
                              for p in paths),encoding="utf-8")
    cmd=[str(FFMPEG),"-nostdin","-hide_banner","-loglevel","error",
         "-f","concat","-safe","0","-i",str(listing),
         "-an","-c:v","copy","-y",str(PREVIEW)]
    p=run_cmd(cmd,timeout=180)
    if p.returncode: raise RuntimeError("Concat failed: "+p.stderr[-700:])
    report["output_validation"]=check_media(PREVIEW)
    report["output_size_bytes"]=PREVIEW.stat().st_size
    report["source_audio_modified"]=False
    report["video_pixel_qa_pass"]=False
    (OUTPUT/"R32_DIAGNOSTIC_QA.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("RG_R32_RENDER_RESULT="+json.dumps(report,sort_keys=True),flush=True)
    if not report["output_validation"]["video_geometry_ok"]:
        raise SystemExit("REJECT_PROXY_WRONG_FRAME_COUNT_OR_DECODE")
    print("RG_R32_V1_PROXY_GEOMETRY_PASS_NOT_RELEASE",flush=True)

if __name__=="__main__":
    main()
