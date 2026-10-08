#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safety-envelope prototype for RG Auto Edit cigarette candidate tracking.

Independent *semantic* cigarette confirmation is NOT provided by this file.
This is a deterministic appearance/motion gate exercised on known synthetic
frames, never a production blur release decision.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np
from norfair_motion_challenge_v1 import make_clip,COUNT,SEED

SCHEMA="RG_OSS_CIGARETTE_MOTION_GATE_V2"
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SCENARIOS=("slow_motion","fast_motion","intermittent_occlusion","lookalike_distractor")

def gate_appearance_motion(frames,seed_bbox,anchor,score_min=0.93,max_prediction_error=8.0):
    """Reject ambiguous reacquisition instead of trusting a matching texture.

    Uses only appearance and motion; neither identity nor cigarette presence is
    confirmed. A missing observation is ALWAYS a reason to block blur export.
    """
    if not frames or not 0<=anchor<len(frames):
        raise ValueError("Seed index invalid")
    x0,y0,x1,y1=map(int,seed_bbox)
    if x1-x0<3 or y1-y0<3 or (x1-x0)*(y1-y0)<30:
        raise ValueError("Unsafe raw seed bbox")
    gray=[cv2.cvtColor(f,cv2.COLOR_BGR2GRAY) for f in frames]
    H,W=gray[0].shape
    if any(im.shape!=(H,W) for im in gray):
        raise ValueError("Frame sizes differ")
    if not (0<=x0<x1<=W and 0<=y0<y1<=H):
        raise ValueError("Seed bbox outside image")
    if not (0.0<score_min<1.0 and 0<max_prediction_error<=25.0):
        raise ValueError("Unsafe acceptance thresholds")
    templ=gray[anchor][y0:y1,x0:x1]
    if float(templ.std())<7.0:
        raise ValueError("Featureless seed patch")
    observations=[]
    for im in gray:
        scores=cv2.matchTemplate(im,templ,cv2.TM_CCOEFF_NORMED)
        _,peak,_,pos=cv2.minMaxLoc(scores)
        observations.append(((pos[0]+templ.shape[1]/2.0,
                              pos[1]+templ.shape[0]/2.0),float(peak)))
    centers=[None]*len(frames)
    reasons=["UNINITIALIZED"]*len(frames)
    centers[anchor]=[(x0+x1)/2.0,(y0+y1)/2.0]
    reasons[anchor]="ACCEPT_TENTATIVE_SEED"
    for direction in (1,-1):
        last_index=anchor
        last_center=centers[anchor]
        velocity=None
        for i in range(anchor+direction,len(frames) if direction>0 else -1,direction):
            center,score=observations[i]
            if not math.isfinite(score) or score<score_min:
                reasons[i]="ABSTAIN_NO_VISUAL_MATCH"
                continue
            delta=i-last_index
            projected=(last_center if velocity is None else
                       [last_center[j]+velocity[j]*delta for j in range(2)])
            tolerance=24.0 if velocity is None else max_prediction_error
            if math.dist(projected,center)>tolerance:
                reasons[i]="ABSTAIN_IDENTITY_AMBIGUOUS"
                continue
            centers[i]=[round(v,3) for v in center]
            reasons[i]="ACCEPT_TENTATIVE"
            measured=[(center[j]-last_center[j])/delta for j in range(2)]
            velocity=(measured if velocity is None else
                      [(velocity[j]+measured[j])/2.0 for j in range(2)])
            last_index=i
            last_center=center
    return {"centers":centers,"reasons":reasons,
            "proven_cigarette_identity":False,
            "semantic_detector_coverage":False,
            "ready_for_production":False}

def score_with_simulated_truth(name):
    frames,seed,truth=make_clip(name)
    track=gate_appearance_motion(frames,seed,SEED)
    pred=track["centers"]
    if len(pred)!=COUNT:raise RuntimeError("Wrong benchmark frame count")
    correct=sum(t is not None and p is not None and math.dist(t,p)<=7.5
                for t,p in zip(truth,pred))
    missed=sum(t is not None and p is None for t,p in zip(truth,pred))
    incorrect=sum(t is not None and p is not None and math.dist(t,p)>7.5
                  for t,p in zip(truth,pred))
    false_matches=sum(t is None and p is not None for t,p in zip(truth,pred))
    abstain=sum(p is None for p in pred)
    unknown=sum(t is None for t in truth)
    return {
        "case":name,"frames":COUNT,
        "truth_visible_frames":COUNT-unknown,
        "truth_absent_frames":unknown,
        "correct_position_frames":correct,
        "missed_visible_frames":missed,
        "incorrect_visible_matches":incorrect,
        "false_matches_when_absent":false_matches,
        "abstained_frames":abstain,
        "safe_against_known_ground_truth":bool(not incorrect and not false_matches),
        "automatic_blur_release":bool(not incorrect and not false_matches and abstain==0
                                      and unknown==0 and correct==COUNT),
        "abstain_reasons":{
           "NO_VISUAL_MATCH":track["reasons"].count("ABSTAIN_NO_VISUAL_MATCH"),
           "IDENTITY_AMBIGUOUS":track["reasons"].count("ABSTAIN_IDENTITY_AMBIGUOUS"),
        },
        "semantic_cigarette_identity_confirmed":False,
    }

def run_report():
    rows=[score_with_simulated_truth(name) for name in SCENARIOS]
    return {
        "schema":SCHEMA,"contour":"auto_edit",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "status":"SYNTHETIC_SAFETY_BENCHMARK_COMPLETED",
        "cases":rows,
        "zero_known_false_positives":all(x["false_matches_when_absent"]==0
                                         and x["incorrect_visible_matches"]==0 for x in rows),
        "all_cases_automatic_release":all(x["automatic_blur_release"] for x in rows),
        "original_audio_modified":False,
        "production_xml_modified":False,
        "mandatory_cigarette_blur_modified":False,
        "production_approved":False,
        "semantic_detection_per_frame":False,
        "source_video_read":False,
        "decision":"SHADOW_ONLY_REQUIRE_SEMANTIC_REDETECTION_AND_REAL_LABELS",
        "limitations":"Appearance/motion matching cannot distinguish a truly identical object reliably. Never use this bench as production object identification.",
    }

def self_check(report):
    if report["schema"]!=SCHEMA or len(report["cases"])!=4:
        raise RuntimeError("Unexpected challenge report")
    expected={
      "slow_motion":(24,0,0,0,0,True),
      "fast_motion":(24,0,0,0,0,True),
      "intermittent_occlusion":(20,0,0,0,4,False),
      "lookalike_distractor":(11,0,0,0,13,False),
    }
    for r in report["cases"]:
        got=(r["correct_position_frames"],r["missed_visible_frames"],
             r["incorrect_visible_matches"],r["false_matches_when_absent"],
             r["abstained_frames"],r["automatic_blur_release"])
        if got!=expected[r["case"]]:
            raise RuntimeError(f"{r['case']} regression changed: got={got}, want={expected[r['case']]}")
    if not report["zero_known_false_positives"] or report["all_cases_automatic_release"]:
        raise RuntimeError("Fail-closed behavior not retained")
    if report["production_approved"] is not False:
        raise RuntimeError("Unsafe production approval")
    return True

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=ROOT/"norfair_motion_safety_gate_v2.json")
    a=ap.parse_args(argv)
    from importlib.metadata import version
    if version("norfair")!="2.3.0" or version("opencv-python")!="4.11.0.86":
        raise RuntimeError("Isolated library versions changed")
    report=run_report()
    self_check(report)
    dst=a.output.resolve()
    if ROOT.resolve() not in dst.parents or dst.suffix.lower()!=".json":
        raise RuntimeError("Output must be isolated F: shadow JSON")
    dst.parent.mkdir(parents=True,exist_ok=True)
    tmp=dst.with_name("."+dst.stem+"."+str(os.getpid())+".tmp")
    try:
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,dst)
    finally:
        if tmp.exists():tmp.unlink()
    print("=== RG NORFAIR MOTION SAFETY GATE V2 RESULT ===",flush=True)
    print(json.dumps({
       "status":report["status"],"cases":[{
          "case":r["case"],"correct":r["correct_position_frames"],
          "missed":r["missed_visible_frames"],"false_positives":r["false_matches_when_absent"],
          "abstained":r["abstained_frames"],"automatic_release":r["automatic_blur_release"]
       } for r in report["cases"]],
       "zero_known_false_positives":report["zero_known_false_positives"],
       "all_cases_automatic_release":report["all_cases_automatic_release"],
       "production_approved":False,"production_modified":False,
       "report":str(dst),
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG NORFAIR MOTION SAFETY GATE V2 STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),"production_modified":False},
                         ensure_ascii=False),flush=True)
        raise SystemExit(2)
