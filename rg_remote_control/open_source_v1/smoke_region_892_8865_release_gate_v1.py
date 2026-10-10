#!/usr/bin/env python3
"""892 smoke-region QA, not a smoke detector. This is a release-blocking test."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import zipfile

SCHEMA="RG_892_SMOKE_REGION_PROBE_V1"
V3B="RG_892_FOURZONE_RESTRICTED_CPU_QA_V3B"
NEG="RG_8865_REAL_101_FRAME_SHIRT_BEHIND_MICROPHONE_PATTERN_SHADOW_QA_V1"
SHAPE=(610,740)
SAMPLES={
  360: {"plume_left":(170,0,330,200),"exhale_face":(410,150,560,325)},
  370: {"plume_left":(170,0,330,200),"exhale_face":(410,150,575,335)},
  380: {"plume_left":(170,0,330,200),"exhale_face":(420,150,580,340)},
  390: {"plume_left":(205,0,335,200)},
}

def in_box(mask,box):
    x1,y1,x2,y2=box
    if not (0<=x1<x2<=mask.shape[1] and 0<=y1<y2<=mask.shape[0]):
        raise ValueError("Invalid bounding box")
    return int(mask[y1:y2,x1:x2].sum())

def audit(zippath,negative_review_path):
    import cv2
    import numpy as np
    with zipfile.ZipFile(zippath) as z:
        if z.testzip() is not None:
            raise ValueError("Corrupted 892 source archive")
        if len(set(z.namelist()))!=len(z.namelist()):
            raise ValueError("Duplicate ZIP members")
        d=json.loads(z.read("report.json"))
        if d.get("schema")!=V3B or len(d.get("rows",[]))!=60:
            raise ValueError("Incorrect V3B input report")
        if d.get("production_release_allowed") is not False or d.get("smoke_identification_verified") is not False:
            raise ValueError("Unsafe V3B metadata")
        if d.get("negative_8865_test_passed") is not False:
            raise ValueError("Unexpected full 8865 negative claim")
        cases=[]
        for idx,boxes in SAMPLES.items():
            row=d["rows"][idx-360]
            if row.get("source_frame")!=idx:
                raise ValueError("Frame alignment mismatch")
            data=np.frombuffer(z.read(f"masks/smoke_unverified_{idx-360:02d}.png"),np.uint8)
            mask=cv2.imdecode(data,cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.shape!=SHAPE:
                raise ValueError("Invalid smoke mask")
            mask=(mask>127).astype(np.uint8)
            if int(mask.sum())!=int(row["smoke_motion_candidate_pixels"]):
                raise ValueError("Mask differs from V3B pixel count")
            for name, box in boxes.items():
                count=in_box(mask,box)
                cases.append({"frame":idx,"region":name,"candidate_pixels":count,
                              "omission":count==0,
                              "pixel_smoke_identity_verified":False})
    neg=json.loads(Path(negative_review_path).read_text(encoding="utf-8-sig"))
    if neg.get("schema")!=NEG:
        raise ValueError("Wrong known 886_5 hard-negative review")
    if neg.get("real_source_images_processed")!=101:
        raise ValueError("Wrong 886_5 sparse sample count")
    if neg.get("full_negative_8865_video_test") is not False or neg.get("quarantine_886_5_unchanged") is not True:
        raise ValueError("Unexpected 886_5 hard-negative release state")
    omissions=[{"frame":x["frame"],"region":x["region"]} for x in cases if x["omission"]]
    return {"schema":SCHEMA,
            "status":"BLOCK_RELEASE_SMOKE_OMISSIONS_AND_8865_NEGATIVE_INCOMPLETE",
            "smoke_coarse_region_count":len(cases),
            "empty_smoke_region_count":len(omissions),
            "smoke_omissions":omissions,
            "smoke_pixel_precision_verified":False,
            "smoke_pixel_recall_verified":False,
            "8865_sparse_negative_reference_frames":101,
            "8865_full_negative_video_test_passed":False,
            "quarantine_886_5_unchanged":True,
            "production_release_allowed":False}

def self_test():
    import numpy as np
    m=np.zeros(SHAPE,np.uint8)
    assert in_box(m,(170,0,330,200))==0
    m[15,200]=1
    assert in_box(m,(170,0,330,200))==1
    assert in_box(m,(410,150,560,325))==0
    try: in_box(m,(10,10,9,9))
    except ValueError: pass
    else: raise AssertionError("Invalid box accepted")
    assert len(SAMPLES)==4 and sum(len(v) for v in SAMPLES.values())==7
    print("RG_SMOKE_892_COARSE_REGION_AND_8865_NEGATIVE_QA_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--zip",type=Path)
    p.add_argument("--negative-review",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    elif a.zip and a.negative_review:
        print(json.dumps(audit(a.zip,a.negative_review),ensure_ascii=False,indent=2))
    else:p.error("Use --self-test or --zip ... --negative-review ...")
