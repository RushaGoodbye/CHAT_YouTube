#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only 904 cigarette QA and completeness forensic, no release override."""
from __future__ import annotations
import json
from pathlib import Path
import re
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
IDs=[1,2,4,5,6,7]
def load(path):
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:return {"error":str(e)[:220]}
def keys(d,arr):
    return {k:d.get(k) for k in arr if k in d}
def qa(i):
    b=f"RG_EDITED_904_{i}"
    q=load(APP/(b+"_CIGARETTE_BLUR_QA.json"))
    d=load(APP/(b+"_CIGARETTE_BLUR_DETECTIONS.json"))
    marker=load(APP/(b+"_CIGARETTE_REVIEW_MARKERS.json"))
    gate=load(APP/(b+"_FINAL_RELEASE_GATE.json"))
    return {"dialogue":i,
            "root_sidecar_exists":(APP/(b+"_CIGARETTE_BLUR_QA.json")).is_file(),
            "folder_sidecar_exists":(APP/"904"/(b+"_CIGARETTE_BLUR_QA.json")).is_file(),
            "qa_keys":sorted(q.keys())[:75],
            "qa_coverage":keys(q.get("coverage_qa") or {},["coverage_ratio","missing_frames","passed"]),
            "qa":keys(q,["schema","passed","status","raw_detection_count","confirmed_track_count",
                         "overlay_count","review_required","review_reasons","failures","unconfirmed_detection_count",
                         "missing_masks","missing_overlay_count","cigarette_blur_enabled"]),
            "det":keys(d,["schema","status","passed","raw_detection_count","confirmed_track_count",
                          "rejected_track_count","failures","unconfirmed_detection_count"]),
            "review_marker_keys":sorted(marker.keys())[:25],
            "review_marker_summary":keys(marker,["schema","status","count","marker_count","review_required"]),
            "release_gate":keys(gate,["passed","status","release_allowed"])}
def main():
    m=load(APP/"RG_EDITED_904_MULTI_DIALOGUE.json")
    qa_files=[qa(i) for i in IDs]
    s=(APP/"rg_studio_postrun.py").read_text(encoding="utf-8-sig")
    lines=s.splitlines()
    def frag(a,b):return "\n".join(f"{i+1}: {lines[i]}" for i in range(a-1,min(len(lines),b)))
    op=(APP/"rg_operations_guard.py").read_text(encoding="utf-8-sig").splitlines()
    k=next((i for i,x in enumerate(op) if x.startswith("def summarize_cigarette_qas")),None)
    print("RG_904_CIGARETTE_QA_CONTENT_AUDIT")
    print(json.dumps({
         "schema":"RG_904_CIGARETTE_QA_CONTENT_AUDIT_V1",
         "stream":"904",
         "manifest_count":m.get("dialogue_count"),
         "manifest_status":m.get("status"),
         "manifest_skipped":m.get("skipped_screenshots"),
         "per_dialogue":qa_files,
         "postrun_expectation_implementation":frag(88,153),
         "postrun_header_and_args":frag(1,87),
         "postrun_footer":frag(153,min(290,len(lines))),
         "operations_guard_summary_implementation":"\n".join(f"{i+1}: {op[i]}" for i in range(k,min(k+70,len(op)))) if k is not None else "not found",
         "read_only":True,
         "production_files_modified":False
    },ensure_ascii=False,indent=2,default=str))
if __name__=="__main__":main()
