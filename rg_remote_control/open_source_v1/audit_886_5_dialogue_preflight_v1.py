#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare a read-only, precise 886_5 cigarette audit from withheld clean XML.

This script NEVER makes a cigarette-detection claim and NEVER releases XML.
It reads the clean Premiere sequence / semantic hold and outputs a bounded
source-time inventory so the next step can inspect ONLY the dialogue, not
the full 886 stream. It does not run inference, read video frames or change
audio, XML or original media.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
HOLD=APP/"886"/"RG_EDITED_886_5.SEMANTIC_HOLD.json"
ROOT_HOLD=APP/"RG_EDITED_886_5.SEMANTIC_HOLD.json"
PRIMARY=APP/"RG_EDITED_886_5.xml"
DELIVERED=APP/"886"/"RG_EDITED_886_5.xml"
DET=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
ENGINE=APP/"rg_cigarette_blur.py"
CONFIG=APP/"rg_auto_edit_config.json"
BACKUP_XML_SHA="1838e6e215b4c0cb132924a1288dc610bf71c2cca393e4e0f6ad66aeab1dfdc0"
OUT=DATA/"oss_shadow"/"audit_plans"/"886_5_semantic_cigarette_preflight_v1.json"
SCHEMA="RG_886_5_REAL_CIGARETTE_AUDIT_PREFLIGHT_V1"

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()

def load_json(path):
    if not path.is_file():
        raise RuntimeError("Required file not found: "+str(path))
    return json.loads(path.read_text(encoding="utf-8-sig"))

def frame_value(s):
    if s is None: return None
    try:
        x=float(s)
        if not math.isfinite(x):return None
        return round(x,3)
    except (ValueError,TypeError):
        return None

def seq_rate(seq):
    rate=seq.find("rate")
    if rate is None:
        return {"frames_per_second":None,"timebase":None,"ntsc":None}
    base=frame_value(rate.findtext("timebase"))
    ntsc=(rate.findtext("ntsc") or "").upper()=="TRUE"
    fps=None if not base or base<=0 else float(base)*(1000/1001 if ntsc else 1)
    return {"frames_per_second":round(fps,6) if fps else None,
            "timebase":base,"ntsc":ntsc}

def clip_fps(clip,default):
    rate=clip.find("rate")
    if rate is None:return default
    base=frame_value(rate.findtext("timebase"))
    if not base or base<=0:return default
    ntsc=(rate.findtext("ntsc") or "").upper()=="TRUE"
    return float(base)*(1000/1001 if ntsc else 1)

def normalize_pathurl(raw):
    if not raw:return None
    raw=raw.strip()
    # URI is retained in the local JSON audit, not printed to console.
    return raw

def get_video_segments(xml_path):
    try:
        root=ET.parse(xml_path).getroot()
    except ET.ParseError as err:
        raise RuntimeError("Clean withheld Premiere XML parse failed: "+str(err)) from err
    if root.tag!="xmeml":
        raise RuntimeError("Expected xmeml, not "+root.tag)
    seq=root.find("sequence")
    if seq is None:raise RuntimeError("Premiere sequence missing")
    rate=seq_rate(seq)
    fps=rate["frames_per_second"]
    tracks=seq.findall("./media/video/track")
    if not tracks:raise RuntimeError("Clean dialogue XML contains no video track")
    segments=[]
    for track_number,track in enumerate(tracks,1):
        for clip in track.findall("clipitem"):
            start=frame_value(clip.findtext("start"))
            end=frame_value(clip.findtext("end"))
            source_in=frame_value(clip.findtext("in"))
            source_out=frame_value(clip.findtext("out"))
            movie_url=normalize_pathurl(clip.findtext("file/pathurl"))
            if not movie_url:
                for node in clip.findall("file"):
                    movie_url=normalize_pathurl(node.findtext("pathurl"))
                    if movie_url:break
            segment={
              "track":track_number,
              "clip_id":clip.get("id"),
              "name":clip.findtext("name"),
              "source_media_reference":movie_url,
              "start_frame":start,
              "end_frame":end,
              "source_in_frame":source_in,
              "source_out_frame":source_out,
            }
            source_fps=clip_fps(clip,fps)
            segment["source_fps"]=round(source_fps,6) if source_fps else None
            if fps and start is not None and end is not None and end>start>=0:
                segment["timeline_interval_seconds"]=[round(start/fps,3),round(end/fps,3)]
            else:
                segment["timeline_interval_seconds"]=None
            if source_fps and source_in is not None and source_out is not None and source_out>source_in>=0:
                segment["source_interval_seconds"]=[round(source_in/source_fps,3),round(source_out/source_fps,3)]
            else:
                segment["source_interval_seconds"]=None
            segments.append(segment)
    duration=frame_value(seq.findtext("duration"))
    end_frames=[s["end_frame"] for s in segments if s["end_frame"] is not None and s["end_frame"]>=0]
    if duration is None and end_frames:duration=max(end_frames)
    total_duration=round(duration/fps,3) if duration is not None and fps else None
    mapped=[s for s in segments if s["source_interval_seconds"] is not None and s["timeline_interval_seconds"] is not None]
    return {
       "sequence_name":seq.findtext("name"),
       "sequence_rate":rate,
       "duration_seconds":total_duration,
       "video_track_count":len(tracks),
       "video_clip_count":len(segments),
       "mapped_clip_count":len(mapped),
       "source_ranges_ready":bool(mapped),
       "segments":segments[:80],
       "segments_truncated":len(segments)>80,
       "note":"Source frame in/out may refer to different original media; never assume a single global stream range without matching clip file references.",
    }

def verify_quarantine():
    hold=load_json(HOLD)
    required={
      "schema":"RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1",
      "status":"QUARANTINED_NOT_READY_FOR_PUBLICATION",
      "stream":"886","dialogue":"886_5",
      "do_not_publish":True,
      "primary_xml_withheld":True,
      "delivered_xml_withheld":True,
    }
    for key,val in required.items():
        if hold.get(key)!=val:raise RuntimeError(f"Quarantine hold mismatch: {key}")
    if PRIMARY.exists() or DELIVERED.exists():
        raise RuntimeError("Candidate 886_5 has been moved into a ready folder; refuse shadow audit")
    if not ROOT_HOLD.is_file():
        raise RuntimeError("Missing root hold marker")
    other=load_json(ROOT_HOLD)
    if other!=hold:raise RuntimeError("Root and delivery hold markers differ")
    clean=Path(str(hold.get("clean_xml_for_semantic_review") or ""))
    backup=Path(str(hold.get("backup_directory") or ""))
    if not clean.is_file() or backup not in clean.parents:
        raise RuntimeError("Verified clean XML absent from quarantine backup directory")
    if digest(clean)!=BACKUP_XML_SHA:
        raise RuntimeError("Clean withheld 886_5 XML SHA changed")
    if clean.name!="CLEAN_XML_PENDING_SEMANTIC_REVIEW.xml":
        raise RuntimeError("Unexpected clean XML filename")
    if not (backup/"primary.xml").is_file() or not (backup/"delivered.xml").is_file():
        raise RuntimeError("Full backup missing original working and delivered XML")
    if not (backup/"MICROPHONE_KNOWN_NEGATIVE_FIXTURE.json").is_file():
        raise RuntimeError("Known microphone-negative fixture missing")
    negative=load_json(backup/"MICROPHONE_KNOWN_NEGATIVE_FIXTURE.json")
    if negative.get("visual_label")!="MICROPHONE_MARK_NOT_CIGARETTE":
        raise RuntimeError("Wrong known-negative fixture label")
    det=load_json(DET);qa=load_json(QA)
    for obj,label in ((det,"detection"),(qa,"blur QA")):
        if obj.get("passed") is not False or obj.get("production_release_allowed") is not False:
            raise RuntimeError(f"{label} wrongly still grants publication")
        if obj.get("semantic_visual_qa")!="FAIL_KNOWN_FALSE_POSITIVE":
            raise RuntimeError(f"{label} semantic fail marker missing")
    return hold,clean,negative

def config_engine_info():
    out={"cigarette_config_present":CONFIG.is_file(),
         "detector_source_present":ENGINE.is_file(),
         "semantic_detector_known_to_be_valid":False,
         "semantic_review_state":"REQUIRED"}
    if CONFIG.is_file():
        opts=(load_json(CONFIG).get("cigarette_blur") or {})
        out["cigarette_blur_version"]=opts.get("version")
        out["mandatory"]=opts.get("mandatory")
        out["fail_closed"]=opts.get("fail_closed")
        out["whole_frame_blur_forbidden"]=opts.get("whole_frame_blur_forbidden")
        out["config_option_names"]=sorted(str(k) for k in opts)[:80]
    if ENGINE.is_file():
        # Read a tiny amount of static source only to list function signatures;
        # DO NOT import modules, instantiate YOLO, or execute detection.
        import ast
        text=ENGINE.read_text(encoding="utf-8-sig",errors="replace")
        tree=ast.parse(text,filename=str(ENGINE))
        names=[]
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                names.append(node.name)
        out["engine_public_function_names"]=names[:80]
        out["engine_sha256"]=digest(ENGINE)
    return out

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUT)
    args=parser.parse_args(argv)
    out=args.output.resolve()
    allowed=(DATA/"oss_shadow").resolve()
    if allowed not in out.parents or out.suffix.lower()!=".json":
        raise RuntimeError("Only isolated F: OSS shadow JSON output allowed")
    hold,xml,negative=verify_quarantine()
    inventory=get_video_segments(xml)
    engine=config_engine_info()
    if not inventory["source_ranges_ready"]:
        state="NEEDS_SOURCE_TIMELINE_INSPECTION"
    else:
        state="AUDIT_INTERVALS_READY_FOR_READ_ONLY_FRAME_SCAN"
    result={
      "schema":SCHEMA,
      "created_utc":datetime.now(timezone.utc).isoformat(),
      "status":state,"contour":"auto_edit","stream":"886","dialogue":"886_5",
      "source_premiere_clean_xml":str(xml),
      "clean_xml_sha256":digest(xml),
      "source_inventory":inventory,
      "detector_inventory":engine,
      "known_negative_microphone":{
        "visual_label":negative["visual_label"],
        "raw_hit_count":len(negative.get("archived_detector_hits") or []),
        "reviewed_window_sec":negative.get("reviewed_window_sec"),
      },
      "source_video_opened":False,
      "semantic_inference_run":False,
      "cigarette_persistence_across_dialogue":"UNKNOWN",
      "whole_dialogue_cigarette_presence":"NOT_YET_DETERMINED",
      "xml_modified":False,
      "audio_modified":False,
      "production_release_allowed":False,
      "hold_left_unchanged":True,
      "next":"Inspect source frame mappings, then run bounded read-only FULL-dialogue smoke detector with microphone-negative verification and independent semantic image review. Do not release 886_5 until that passes."
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name("."+out.stem+"."+str(os.getpid())+".tmp")
    try:
        tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,out)
    finally:
        if tmp.is_file():tmp.unlink()
    print("=== RG 886_5 SEMANTIC DIALOGUE PREFLIGHT RESULT ===",flush=True)
    print(json.dumps({
        "status":state,
        "contour":"auto_edit",
        "sequence_duration_seconds":inventory["duration_seconds"],
        "video_clips":inventory["video_clip_count"],
        "mapped_source_clips":inventory["mapped_clip_count"],
        "video_tracks":inventory["video_track_count"],
        "cigarette_blur_engine":engine.get("cigarette_blur_version"),
        "microphone_negative_raw_hits":len(negative.get("archived_detector_hits") or []),
        "whole_dialogue_semantic_scan_done":False,
        "publication_allowed":False,
        "production_modified":False,
        "result":str(out)
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("=== RG 886_5 SEMANTIC DIALOGUE PREFLIGHT STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),"production_modified":False},
                         ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
