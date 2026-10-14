#!/usr/bin/env python3
"""R26.2 SHADOW: build conservative per-frame masks from VERIFIED sightings.

The caller supplies one verified object box per visible frame. No prediction,
no gap-filling, no semantic model, no alteration to Premiere/MP4/audio.
Output can feed r26_presence_gate_8866.evaluate. A known cut forces a split.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

from r26_presence_gate_8866 import SCHEMA, OBJECTS, SIDES, _box

def build(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Incompatible evidence schema")
    n = data.get("frame_count")
    w, h = data.get("width"), data.get("height")
    if any(type(x) is not int or x <= 0 for x in (n,w,h)):
        raise ValueError("Missing valid frame count and dimensions")
    cuts = data.get("cut_frames", [])
    if not isinstance(cuts,list) or any(type(c) is not int or not 0 < c < n for c in cuts):
        raise ValueError("Invalid cuts")
    if len(set(cuts)) != len(cuts):
        raise ValueError("Duplicate cuts")
    required = data.get("required_pairs", [])
    if not required or any(not isinstance(p,dict) or p.get("participant") not in SIDES or p.get("object") not in OBJECTS for p in required):
        raise ValueError("Invalid required object pairs")
    pairs = {(p["participant"],p["object"]) for p in required}
    if len(pairs) != len(required):
        raise ValueError("Duplicate pairs")
    by_key = {}
    for row in data.get("evidence", []):
        if not isinstance(row,dict):raise ValueError("Bad evidence row")
        frame,side,obj=row.get("frame"),row.get("participant"),row.get("object")
        if type(frame) is not int or not 0 <= frame < n or (side,obj) not in pairs:
            raise ValueError("Bad evidence identity or frame")
        key=(frame,side,obj)
        if key in by_key:raise ValueError("Duplicate evidence")
        state=row.get("presence")
        if state not in ("present","absent","unknown"):
            raise ValueError("Bad presence state")
        if state=="present" and row.get("semantic_verified") is True:
            bbox=_box(row.get("bbox"),w,h,"positive")
            by_key[key]=list(bbox)
        else:
            if state != "present" and row.get("bbox") is not None:
                raise ValueError("Absent or unknown object must not have bbox")
            by_key[key]=None
    # Emit one *frame-long* box per independently verified sighting.
    # Safe conservative default: never track through missing observations.
    masks=[]
    for (f,side,obj),box in sorted(by_key.items()):
        if box is not None:
            masks.append({"start":f,"end":f+1,"participant":side,
                          "object":obj,"bbox":box})
    result=dict(data)
    if data.get("masks"):
        raise ValueError("Refuse to replace existing candidate masks")
    result["masks"]=masks
    result["candidate_generation"]="VERIFIED_PER_FRAME_NO_PREDICTION"
    result["candidate_release_approved"]=False
    result["audio_modified"]=False
    result["source_modified"]=False
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.input.resolve()==a.output.resolve() or a.output.suffix.lower()!=".json":
        raise SystemExit("Output must be a new JSON")
    d=build(json.loads(a.input.read_text(encoding="utf-8-sig")))
    # Fail before writing any candidate with semantically incomplete evidence.
    from r26_presence_gate_8866 import evaluate
    qa=evaluate(d)
    if not qa["structural_candidate_pass"]:
        raise SystemExit("REFUSED: missing/ambiguous object-frame evidence or protected overlap: "+str(qa["issues_by_kind"]))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("R26.2_SHADOW_FRAME_MASK_CANDIDATE_PASS",qa["required_object_frame_checks"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
