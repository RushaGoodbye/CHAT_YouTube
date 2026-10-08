#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RG Auto Edit: Norfair 2.3.0 SHADOW evaluation of saved cigarette detections.

Reads only existing 886_5 current QA and pre-fix raw detections. Does not
access the stream video, detector, audio, Premiere XML, or production code.
The result is diagnostic; a matching Norfair track is NOT production clearance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
BACKUP=DATA/"release_backups"/"PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648"
RAW=BACKUP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
CURRENT=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json"
QA=APP/"RG_EDITED_886_5_CIGARETTE_BLUR_QA.json"
OUTPUT=DATA/"oss_shadow"/"norfair_886_5_v1.json"

def load(path):
    if not path.is_file():
        raise RuntimeError(f"Expected evidence file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda:stream.read(1<<20),b""):
            h.update(data)
    return h.hexdigest()

def validate_evidence(raw,current,qa,raw_sha):
    if raw.get("status")!="AMBIGUOUS" or raw.get("passed") is not False:
        raise RuntimeError("Pre-fix evidence changed")
    if int(raw.get("raw_detection_count") or 0)!=2:
        raise RuntimeError("Pre-fix raw detection count is not 2")
    rejected=raw.get("rejected_tracks") or []
    if len(rejected)!=1 or len(rejected[0].get("hits") or [])!=2:
        raise RuntimeError("Expected one rejected original track with 2 raw hits")
    if str(current.get("original_detection_report_sha256"))!=raw_sha:
        raise RuntimeError("Pre-fix evidence checksum does not match repair record")
    if current.get("passed") is not True or current.get("status")!="TRACKED":
        raise RuntimeError("Current confirmed blur evidence missing")
    if int(current.get("confirmed_track_count") or 0)!=1:
        raise RuntimeError("Expected exactly one current confirmed track")
    if not any(t.get("confirmation")=="SHORT_STABLE" for t in (current.get("tracks") or [])):
        raise RuntimeError("Existing SHORT_STABLE confirmation missing")
    if qa.get("passed") is not True or int(qa.get("overlay_count") or 0)!=3:
        raise RuntimeError("Existing 886_5 local blur QA no longer passes")
    if (qa.get("coverage_qa") or {}).get("passed") is not True:
        raise RuntimeError("Current coverage QA missing")
    hits=sorted(rejected[0]["hits"],key=lambda h:float(h["t"]))
    if [str(h.get("class")) for h in hits]!=["smoking cigarette","smoking cigarette"]:
        raise RuntimeError("Raw detection class changed")
    for hit in hits:
        bbox=hit.get("bbox") or []
        if len(bbox)!=4 or not all(math.isfinite(float(x)) for x in bbox):
            raise RuntimeError("Invalid original bbox")
        x0,y0,x1,y1=map(float,bbox)
        if not (0<=x0<x1<=1920 and 0<=y0<y1<=1080):
            raise RuntimeError("Invalid bbox geometry")
        score=float(hit.get("score") or 0)
        if not math.isfinite(score) or score<0.08:
            raise RuntimeError("Original cigarette detection too uncertain")
    dt=float(hits[1]["t"])-float(hits[0]["t"])
    if not (0.05<=dt<0.10):
        raise RuntimeError("Expected short-stable temporal spacing")
    return hits

def run_norfair_shadow(hits):
    import numpy as np
    from norfair import Detection, Tracker
    from importlib.metadata import version
    if version("norfair")!="2.3.0":
        raise RuntimeError("Norfair 2.3.0 pin mismatch")
    tracker=Tracker(distance_function="euclidean",
                    distance_threshold=120.0,
                    hit_counter_max=4,
                    initialization_delay=1)
    observations=[]
    fingerprints=[]
    for hit in hits:
        x0,y0,x1,y1=map(float,hit["bbox"])
        center=[(x0+x1)/2,(y0+y1)/2]
        score=float(hit["score"])
        det=Detection(points=np.asarray([center],dtype=np.float32),
                      scores=np.asarray([score],dtype=np.float32),
                      data={"class":hit["class"]})
        live=tracker.update(detections=[det])
        internal=tracker.tracked_objects
        fingerprints.append({
          "internal_count":len(internal),
          "initializing_ids":[int(x.initializing_id) if x.initializing_id is not None else None for x in internal],
          "confirmed_ids":[int(x.id) if x.id is not None else None for x in internal],
        })
        observations.append({
          "t":round(float(hit["t"]),5),
          "center":[round(float(v),2) for v in center],
          "original_score":round(score,5),
          "returned_tracker_ids":[int(obj.id) for obj in live if obj.id is not None],
        })
    centers=[o["center"] for o in observations]
    displacement=math.dist(*centers)
    same_internal_object=(
      len(fingerprints)==2 and all(x["internal_count"]==1 for x in fingerprints)
      and fingerprints[0]["initializing_ids"][0] is not None
      and fingerprints[0]["initializing_ids"][0]==fingerprints[1]["initializing_ids"][0]
      and len(observations[-1]["returned_tracker_ids"])==1
    )
    result="CONSISTENT" if same_internal_object else "INCONCLUSIVE"
    return {
      "status":result,"matched_one_object":same_internal_object,
      "center_displacement_px":round(displacement,3),
      "norfair_tracker_distance_threshold_px":120,
      "observations":observations,"internal_debug":fingerprints,
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    args=parser.parse_args()
    raw=load(RAW);current=load(CURRENT);qa=load(QA)
    raw_hash=sha(RAW)
    hits=validate_evidence(raw,current,qa,raw_hash)
    result=run_norfair_shadow(hits)
    out=args.output.resolve()
    root=(DATA/"oss_shadow").resolve()
    if out.suffix.lower()!=".json" or root not in out.parents:
        raise RuntimeError("Output must be a JSON report inside isolated OSS shadow directory")
    report={
      "schema":"RG_NORFAIR_886_5_SHADOW_V1",
      "date_utc":datetime.now(timezone.utc).isoformat(),
      "contour":"auto_edit",
      "library":"norfair",
      "library_version":"2.3.0",
      "inputs":{
        "original_evidence_sha256":raw_hash,
        "current_status":current["status"],
        "current_cigarette_qa":"PASS",
        "original_detection_count":2
      },
      "tracker":result,
      "production_adopted":False,
      "run_full_video":False,
      "xml_modified":False,
      "audio_modified":False,
      "cigarette_blur_modified":False,
      "critical_limit":"2 detection points do not prove robust tracking of a moving cigarette; must test occlusions and motion on labeled frames before production",
      "decision":"STAY_SHADOW",
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name("."+out.stem+"."+str(os.getpid())+".tmp")
    try:
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,out)
    finally:
        if tmp.exists():tmp.unlink()
    print("=== RG NORFAIR 886_5 SHADOW RESULT ===",flush=True)
    print(json.dumps({
      "status":result["status"],
      "matched_one_object":result["matched_one_object"],
      "original_hit_count":2,
      "distance_px":result["center_displacement_px"],
      "full_video_processed":False,
      "production_modified":False,
      "xml_modified":False,
      "output":str(out)
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("=== RG NORFAIR 886_5 SHADOW STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","error":repr(exc),"production_modified":False},
                         ensure_ascii=False,indent=2),flush=True)
        raise SystemExit(2)
