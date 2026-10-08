#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""886_5 read-only authentic-source contact pack, not a cigarette detector.

Extracts ~one frame per 4s from verified 886.mp4 source ranges used by the
withheld clean 886_5 Premiere timeline. Resolves clip file references by id,
groups bounded intervals, draws labelled overview contact sheets, bundles one
ZIP for visual triage. Never writes XML, auto releases, modifies source media
or pretends interval sampling can prove complete cigarette coverage.

The two microphone detections remain confirmed false positives. All frames
are UNLABELLED and all semantic QA statuses remain FAIL / HOLD.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import unquote,urlparse
import xml.etree.ElementTree as ET
import zipfile
import cv2
import numpy as np

import audit_886_5_dialogue_preflight_v1 as prior
SCHEMA="RG_886_5_SOURCE_CIGARETTE_TRIAGE_V1"
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
ROOT=DATA/"oss_shadow"/"real_8865_semantic_review_v1"
VIDEO=Path(r"\\Desktop-v7gg0en\record\886.mp4")
FFMPEG=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE")
SAMPLE_SECONDS=4.0
MAX_DECODE_DURATION=540.0
MAX_FRAMES=160
MAX_WINDOWS=16
SHEET_COLUMNS=3
SHEET_ROWS=3
SHEET_CELL_W=640
SHEET_CELL_H=385
FRAME_W=1280
FRAME_H=720
SEED_WINDOW=9559.0
SOURCE_MEDIA_NAME="886.mp4"

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):h.update(x)
    return h.hexdigest()

def path_from_uri(raw):
    if not raw:return ""
    raw=str(raw).strip()
    parsed=urlparse(raw)
    if parsed.scheme.lower()=="file":
        path=unquote(parsed.path or "")
        if parsed.netloc:path="//"+parsed.netloc+path
        return path.replace("\\","/")
    return unquote(raw).replace("\\","/")

def media_paths(root):
    """File references often appear once with pathurl, later only <file id>."""
    mapping={}
    for node in root.findall(".//file"):
        fid=node.get("id")
        url=node.findtext("pathurl")
        if fid and url:
            norm=path_from_uri(url)
            previous=mapping.get(fid)
            if previous and previous!=norm:
                raise RuntimeError("Same Premiere file id resolves to conflicting source paths")
            mapping[fid]=norm
    return mapping

def frame_float(raw):
    try:
        v=float(raw)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):
        return None

def rate(node,default):
    fps=prior.clip_fps(node,default)
    if fps is None or not 1<=fps<=240:
        raise RuntimeError("Invalid Premiere source frame rate")
    return fps

def flatten_timeline(xml_bytes):
    root=ET.fromstring(xml_bytes)
    seq=root.find("sequence")
    if seq is None:raise RuntimeError("XML missing Premiere sequence")
    sr=prior.seq_rate(seq)
    fps=sr["frames_per_second"]
    if fps is None or not 20<=fps<=120:
        raise RuntimeError("Unexpected dialogue timebase")
    references=media_paths(root)
    segments=[]
    unknown=[]
    media={}
    for trackidx,track in enumerate(seq.findall("./media/video/track"),1):
        for c in track.findall("clipitem"):
            fileNode=c.find("file")
            ref=fileNode.get("id") if fileNode is not None else None
            path=path_from_uri(fileNode.findtext("pathurl")) if fileNode is not None else ""
            if not path and ref:path=references.get(ref,"")
            if not path:
                # In some XMLs the item references a preceding clip's <file>.
                # Cannot certify that the source path is 886.mp4 in that case.
                unknown.append({"track":trackidx,"clip":c.get("id"),"reason":"MISSING_MEDIA_FILE_PATH"})
                continue
            name=Path(path).name.lower()
            media[name]=media.get(name,0)+1
            start,end,si,so=[frame_float(c.findtext(k)) for k in ("start","end","in","out")]
            if any(z is None for z in (start,end,si,so)) or not (0<=start<end and 0<=si<so):
                unknown.append({"track":trackidx,"clip":c.get("id"),"reason":"MISSING_OR_INVALID_CLIP_FRAME_RANGE","media":name})
                continue
            sfps=rate(c,fps)
            ts,te=start/fps,end/fps
            source_start,source_end=si/sfps,so/sfps
            if te-ts<=0 or source_end-source_start<=0:
                raise RuntimeError("Bad Premiere span")
            speed=(source_end-source_start)/(te-ts)
            # Do not pretend reverse, speed-ramped or extreme clips have
            # a simple one-to-one source mapping.
            if speed<=0 or speed>5:
                unknown.append({"track":trackidx,"clip":c.get("id"),"reason":"UNSAFE_TIMEWARP","media":name})
                continue
            segments.append({"track":trackidx,"id":c.get("id"),
                            "source_file":name,"media_path":path,
                            "timeline":[round(ts,5),round(te,5)],
                            "source":[round(source_start,5),round(source_end,5)],
                            "speed":round(speed,6)})
    if not segments:raise RuntimeError("No mapped video clips in withheld sequence")
    dur=frame_float(seq.findtext("duration"))
    duration=dur/fps if dur is not None else max(s["timeline"][1] for s in segments)
    if not 5<=duration<=1200:raise RuntimeError("Unexpected dialogue duration")
    selected=[s for s in segments if s["source_file"]==SOURCE_MEDIA_NAME]
    if not selected:raise RuntimeError("No verified 886.mp4 source clips in Premiere sequence")
    # Same filename does NOT prove the same video. Never mix multiple
    # distinct source path strings into one sampled UNC source file.
    source_paths=set(x["media_path"].casefold() for x in selected)
    sample_candidates=[]
    t=0.0
    while t<duration:
        active=[x for x in selected if x["timeline"][0]-1e-4<=t<x["timeline"][1]+1e-4]
        for clip in active:
            t0,t1=clip["timeline"]
            a,b=clip["source"]
            source_sec=a+(t-t0)*clip["speed"]
            if a-0.05<=source_sec<=b+0.05 and source_sec>=0:
                sample_candidates.append(source_sec)
        t+=SAMPLE_SECONDS
    ranges=[x["source"] for x in selected]
    windows=merge_ranges(ranges,allowed_gap=3.0)
    unique_duration=sum(b-a for a,b in windows)
    anchor=any(a-3<=SEED_WINDOW<=b+3 for a,b in windows)
    # Avoid inferring a verified temporal coverage statement from just
    # "233/233 mapped source ranges": source paths and timeline overlaps matter.
    unknown_886=[s for s in unknown if s.get("media") in (None,SOURCE_MEDIA_NAME)]
    return {
      "timeline_duration":round(duration,3),
      "fps":fps,
      "media_clip_counts":media,
      "source_clips":len(selected),
      "distinct_886_media_paths":len(source_paths),
      "all_mapped_clips":len(segments),
      "unresolved":unknown[:20],
      "unresolved_count":len(unknown),
      "unresolved_886_source_count":len(unknown_886),
      "original_seed_time_covered":anchor,
      "ranges":[[round(a,3),round(b,3)] for a,b in windows],
      "source_range_union_sec":round(unique_duration,3),
      "proposed_timeline_samples":len(sample_candidates),
      "sampling_limit":"One frame per 4 sec is only visual TRIAGE, not exhaustive cigarette validation"
    }

def merge_ranges(ranges,allowed_gap=3):
    valid=[]
    for a,b in ranges:
        a,b=float(a),float(b)
        if not all(math.isfinite(z) for z in (a,b)) or a<0 or b<=a:
            raise RuntimeError("Invalid source video interval")
        valid.append((a,b))
    valid.sort()
    result=[]
    for a,b in valid:
        if result and a<=result[-1][1]+allowed_gap:
            result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:
            result.append((a,b))
    return result

def safe_to_decode(info):
    """Strict sample feasibility; failure leaves an XML-only diagnostic."""
    reason=[]
    if info["unresolved_count"]>0:reason.append("UNRESOLVED_MEDIA_MAPPINGS")
    if info["distinct_886_media_paths"]!=1:reason.append("AMBIGUOUS_OR_MULTIPLE_886_SOURCE_FILES")
    if info["source_range_union_sec"]>MAX_DECODE_DURATION:
        reason.append("TOO_MUCH_SOURCE_DECODING_FOR_SHADOW_SCAN")
    if len(info["ranges"])>MAX_WINDOWS:
        reason.append("TOO_MANY_DISJOINT_SOURCE_WINDOWS")
    if not info["original_seed_time_covered"]:
        reason.append("KNOWN_MICROPHONE_NEGATIVE_SEED_NOT_IN_MAPPED_SOURCE_RANGE")
    estimated=sum(int(math.ceil((b-a)/SAMPLE_SECONDS)) for a,b in info["ranges"])
    if estimated>MAX_FRAMES:reason.append("TOO_MANY_FRAMES_FOR_BOUNDED_REVIEW")
    # The original stream reference is verified in the parsed XML by filename,
    # but the one known UNC source is still checked independently.
    return reason,estimated

def check_reference_source(raw_windows):
    if not VIDEO.is_file() or not FFMPEG.is_file():
        raise RuntimeError("Known original video or FFmpeg missing on AlexPC")
    if not raw_windows:
        raise RuntimeError("No source video windows")

def make_contact(frame_paths,first_time,outdir):
    contact=[]
    canvas=np.full((SHEET_ROWS*SHEET_CELL_H,
                    SHEET_COLUMNS*SHEET_CELL_W,3),24,dtype=np.uint8)
    for i,path in enumerate(frame_paths):
        image=cv2.imread(str(path),cv2.IMREAD_COLOR)
        if image is None or image.shape[:2]!=(FRAME_H,FRAME_W):
            raise RuntimeError("Unexpected sampled JPEG geometry")
        tile=np.full((SHEET_CELL_H,SHEET_CELL_W,3),18,dtype=np.uint8)
        overview=cv2.resize(image,(SHEET_CELL_W,360),interpolation=cv2.INTER_AREA)
        tile[:360,:]=overview
        label=f"886_5  SOURCE ~{first_time[i]:.1f}s  UNLABELLED"
        cv2.putText(tile,label,(8,377),cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,(235,235,235),1,cv2.LINE_AA)
        row=(i%(SHEET_COLUMNS*SHEET_ROWS))//SHEET_COLUMNS
        col=i%SHEET_COLUMNS
        canvas[row*SHEET_CELL_H:(row+1)*SHEET_CELL_H,
               col*SHEET_CELL_W:(col+1)*SHEET_CELL_W]=tile
        if i%(SHEET_COLUMNS*SHEET_ROWS)==SHEET_COLUMNS*SHEET_ROWS-1 or i==len(frame_paths)-1:
            out=outdir/f"886_5_CONTACT_{len(contact)+1:02d}.jpg"
            if not cv2.imwrite(str(out),canvas,[cv2.IMWRITE_JPEG_QUALITY,87]):
                raise RuntimeError("Cannot write contact sheet")
            contact.append(out)
            canvas[:]=24
    return contact

def decode_ranges(info,folder):
    out=[]
    for k,(a,b) in enumerate(info["ranges"],1):
        duration=b-a
        if duration<0.04:
            continue
        pattern=folder/f"RAW_SOURCE_{k:02d}_%04d.jpg"
        cmd=[str(FFMPEG),"-nostdin","-hide_banner","-loglevel","error",
             "-ss",f"{a:.3f}","-i",str(VIDEO),"-t",f"{duration:.3f}",
             "-an","-sn","-vf",f"fps=1/{SAMPLE_SECONDS:g},scale={FRAME_W}:{FRAME_H}",
             "-q:v","5","-frames:v",str(MAX_FRAMES),
             "-y",str(pattern)]
        try:
            p=subprocess.run(cmd,capture_output=True,text=True,
                encoding="utf-8",errors="replace",timeout=240,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg read-only frame sampling timed out") from None
        if p.returncode!=0:
            raise RuntimeError("FFmpeg read-only sampling failed: "+p.stderr[-1000:])
        found=sorted(folder.glob(f"RAW_SOURCE_{k:02d}_*.jpg"))
        for j,file in enumerate(found):
            out.append((file,round(a+j*SAMPLE_SECONDS,3)))
        if len(out)>MAX_FRAMES:
            raise RuntimeError("More than maximum allowed sampled frames")
    if not out:raise RuntimeError("No real video frames produced")
    return out

def self_test():
    from xml.etree.ElementTree import fromstring
    orig=fromstring("""<xmeml><sequence><duration>300</duration>
      <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media>
      <video><track><clipitem id="one"><start>0</start><end>150</end>
      <in>285000</in><out>285150</out>
      <file id="source-1"><pathurl>file:///F:/record/886.mp4</pathurl></file>
      </clipitem><clipitem id="two"><start>150</start><end>300</end>
      <in>285150</in><out>285300</out><file id="source-1"/>
      </clipitem></track></video></media></sequence></xmeml>""")
    result=flatten_timeline(ET.tostring(orig))
    assert result["timeline_duration"]==10
    assert result["source_clips"]==2 and result["unresolved_count"]==0
    assert result["distinct_886_media_paths"]==1
    assert result["source_range_union_sec"]==10
    assert result["ranges"]==[[9500.0,9510.0]]
    assert not result["original_seed_time_covered"]
    # Overlapping sources do not artificially double decode volume.
    assert merge_ranges([[8,11],[0,4],[3,9]])==[(0,11)]
    assert merge_ranges([[0,1],[6,7]])==[(0,1),(6,7)]
    # File refs with missing IDs must not silently become known 886.mp4.
    items=orig.findall("./sequence/media/video/track/clipitem")
    items[1].find("file").set("id","unresolvable-file-ref")
    r=flatten_timeline(ET.tostring(orig))
    assert r["unresolved_count"]==1 and r["source_clips"]==1
    assert "UNRESOLVED_MEDIA_MAPPINGS" in safe_to_decode(r)[0]
    # A cap above 540 seconds must be refused, never decode hours.
    oversized=dict(result,source_range_union_sec=541,
                   original_seed_time_covered=True)
    assert "TOO_MUCH_SOURCE_DECODING_FOR_SHADOW_SCAN" in safe_to_decode(oversized)[0]
    print("RG_886_5_UNION_SOURCE_MEDIA_TIMELINE_AND_NEGATIVE_SELFTEST: PASS",flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test()
        return
    hold,xml,negative=prior.verify_quarantine()
    if ROOT.exists() and any(ROOT.iterdir()):
        existing=ROOT/"review_manifest.json"
        if existing.is_file():
            prior_run=json.loads(existing.read_text(encoding="utf-8-sig"))
            if prior_run.get("schema")==SCHEMA:
                print("=== RG 886_5 TRIAGE PREVIOUS REPORT EXISTS ===",flush=True)
                print(json.dumps({"status":prior_run.get("status"),
                     "manifest":str(existing),
                     "zip":str(ROOT/"RG_886_5_REAL_CIGARETTE_VISUAL_TRIAGE.zip"),
                     "production_modified":False,
                     "release_allowed":False},ensure_ascii=False,indent=2),flush=True)
                return
        raise RuntimeError("Existing output dir differs from pinned review; no overwrite")
    ROOT.mkdir(parents=True,exist_ok=True)
    info=flatten_timeline(xml.read_bytes())
    reasons,estimated=safe_to_decode(info)
    note={
      "schema":SCHEMA,"created_utc":datetime.now(timezone.utc).isoformat(),
      "stream":"886","dialogue":"886_5","contour":"auto_edit",
      "original_audio_modified":False,"source_video_modified":False,
      "xml_modified":False,"production_modified":False,
      "semantic_review_complete":False,"release_allowed":False,
      "candidate_detector_run":False,"verified_cigarettes":0,
      "known_false_positive_microphone":True,
      "source_mapping":info,
      "sampling_seconds":SAMPLE_SECONDS,
      "estimated_frame_count":estimated,
      "review_limitations":"Sampling every four seconds cannot certify the complete 356-second dialogue or identify all briefly visible cigarettes."
    }
    if reasons:
        note["status"]="SOURCE_MAPPING_REQUIRES_ATTENTION"
        note["scan_blockers"]=reasons
        save_manifest(note)
        print("=== RG 886_5 SOURCE SAMPLING MAPPING STOPPED ===",flush=True)
        print(json.dumps({
          "status":note["status"],"reasons":reasons,
          "timeline_duration":info["timeline_duration"],
          "source_clips":info["source_clips"],
          "unresolved":info["unresolved_count"],
          "distinct_media":info["media_clip_counts"],
          "source_range_union_sec":info["source_range_union_sec"],
          "source_windows":len(info["ranges"]),
          "production_modified":False,
          "report":str(ROOT/"review_manifest.json")
        },ensure_ascii=False,indent=2),flush=True)
        return
    check_reference_source(info["ranges"])
    with tempfile.TemporaryDirectory(prefix="rg_8865_triage_",dir=str(ROOT)) as td:
        result=decode_ranges(info,Path(td))
        frame_dir=ROOT/"frames"
        frame_dir.mkdir(exist_ok=True)
        frames=[]
        for k,(p,t) in enumerate(result,1):
            dst=frame_dir/f"886_5_{k:03d}.jpg"
            shutil.copyfile(p,dst)
            frames.append((dst,t))
        contact_dir=ROOT/"contact_sheets"
        contact_dir.mkdir(exist_ok=True)
        sheets=make_contact([p for p,t in frames],[t for p,t in frames],contact_dir)
    note.update({
       "status":"SOURCE_FRAME_TRIAGE_READY_NOT_SEMANTICALLY_VERIFIED",
       "sampled_frames":len(frames),"contact_sheets":len(sheets),
       "frame_timestamp_precision":"APPROXIMATE: FFmpeg fps resampling from source intervals, not frame-accurate timeline GT",
       "raw_frames":[{"filename":p.name,"source_time_sec_approx":t} for p,t in frames],
       "contact_sheet_names":[p.name for p in sheets],
       "next":"Upload ZIP to ChatGPT for real-frame review. Identifying potential cigarette appearances on sampled images is not proof of complete coverage. Full resolution + detector precision/recall and frame-level QA remain required.",
    })
    save_manifest(note)
    archive=ROOT/"RG_886_5_REAL_CIGARETTE_VISUAL_TRIAGE.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        z.write(ROOT/"review_manifest.json","review_manifest.json")
        for p,t in frames:z.write(p,"frames/"+p.name)
        for p in sheets:z.write(p,"contact_sheets/"+p.name)
    print("=== RG 886_5 REAL VISUAL TRIAGE PACK COMPLETE ===",flush=True)
    print(json.dumps({
      "status":note["status"],
      "dialogue_duration_seconds":info["timeline_duration"],
      "source_clips":info["source_clips"],
      "source_windows":len(info["ranges"]),
      "sampled_source_frames":len(frames),
      "contact_sheets":len(sheets),
      "zip":str(archive),
      "zip_size_mb":round(archive.stat().st_size/1024**2,2),
      "publication_allowed":False,"complete_semantic_qa":False,
      "production_modified":False
    },ensure_ascii=False,indent=2),flush=True)

def save_manifest(obj):
    path=ROOT/"review_manifest.json"
    tmp=path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("=== RG 886_5 SOURCE CIGARETTE TRIAGE STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),
            "production_modified":False,"release_allowed":False},
            ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
