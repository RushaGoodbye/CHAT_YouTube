#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded challenging-motion benchmark using already-installed Norfair and OpenCV.

No video file input, no network, no pip, no GPU, no Premiere/XML edits.
The benchmark has independent known simulated ground truth, unlike previous
real-video template-only pilot. It cannot certify cigarette identity in video.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import cv2
from norfair_real_motion_8865_v1 import match_track, norfair_probe

DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"oss_shadow"
SCHEMA="RG_OSS_NORFAIR_MOTION_CHALLENGE_V1"
SIZE=(280,420)
COUNT=24
SEED=5
BW=32
BH=10

def make_clip(name):
    rng=np.random.default_rng(20261008)
    patch=rng.integers(45,240,size=(BH,BW),dtype=np.uint8)
    frames=[]
    truth=[]
    for n in range(COUNT):
        background=np.full(SIZE,19,dtype=np.uint8)
        fast=name in ("fast_motion","intermittent_occlusion","lookalike_distractor")
        x=70+(14*n if fast else 3*n)
        y=80+(6*n if fast else 2*n)
        if fast: # keep entire test in range without wrapping
            x=70+int(9*n)
            y=80+int(4*n)
        visible=not (name=="intermittent_occlusion" and 11<=n<=14)
        if name=="lookalike_distractor" and n>=11:
            visible=False
        if visible:
            background[y:y+BH,x:x+BW]=patch
            truth.append([x+BW/2,y+BH/2])
        else:
            truth.append(None)
        if name=="lookalike_distractor" and n>=11:
            # Duplicate identical texture at a different, still nearby position:
            # this is a hard negative, not a valid reacquired original object.
            fake_x=min(x+25,SIZE[1]-BW-1)
            background[y:y+BH,fake_x:fake_x+BW]=patch
        frames.append(cv2.cvtColor(background,cv2.COLOR_GRAY2BGR))
    # Actual seed box must come from known simulated target, not guessed output.
    sx=70+(9*SEED if name!="slow_motion" else 3*SEED)
    sy=80+(4*SEED if name!="slow_motion" else 2*SEED)
    return frames,[sx,sy,sx+BW,sy+BH],truth

def analyze(name):
    frames,seed,truth=make_clip(name)
    track=match_track(frames,seed,SEED)
    out=track["centers"]
    if len(out)!=COUNT:raise RuntimeError("Tracker returned wrong frame count")
    correct=0;missed=0;false_matches=0;bad_matches=0
    for gt,pred in zip(truth,out):
        if gt is None:
            if pred is not None:false_matches+=1
        elif pred is None:
            missed+=1
        elif math.dist(gt,pred)<=7.5:
            correct+=1
        else:
            bad_matches+=1
    true_frames=sum(gt is not None for gt in truth)
    nf=norfair_probe(track)
    # A confirmed ID can belong to a false match, so never use continuity
    # alone to approve identity, cigarette blur or whole-frame coverage.
    full_accuracy=(true_frames>0 and correct==true_frames and missed==0 and bad_matches==0)
    no_false_matches=false_matches==0
    return {
      "case":name,
      "frames":COUNT,
      "truth_visible_frames":true_frames,
      "correct_position_frames":correct,
      "missed_visible_frames":missed,
      "incorrect_visible_matches":bad_matches,
      "false_matches_when_absent":false_matches,
      "norfair_distinct_ids":nf["distinct_confirmed_track_ids"],
      "norfair_single_id":nf["one_id_continuity"],
      "matched_all_visible_ground_truth":full_accuracy,
      "rejects_occluded_or_replaced_object":no_false_matches,
      "candidate_valid_for_case":bool(full_accuracy and no_false_matches),
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=ROOT/"norfair_motion_challenge_v1.json")
    a=p.parse_args()
    target=a.output.resolve()
    if ROOT.resolve() not in target.parents or target.suffix!=".json":
        raise RuntimeError("Output must be isolated shadow JSON on F:")
    from importlib.metadata import version
    if version("norfair")!="2.3.0" or version("opencv-python")!="4.11.0.86":
        raise RuntimeError("Isolated library version mismatch")
    names=("slow_motion","fast_motion","intermittent_occlusion","lookalike_distractor")
    cases=[]
    for name in names:
        entry=analyze(name)
        cases.append(entry)
        print("RG_CHALLENGE|"+name+"|"+
              json.dumps({
                "correct":entry["correct_position_frames"],
                "misses":entry["missed_visible_frames"],
                "false_positives":entry["false_matches_when_absent"]
              },separators=(",",":")),flush=True)
    report={
        "schema":SCHEMA,"date_utc":datetime.now(timezone.utc).isoformat(),
        "contour":"auto_edit","status":"BENCHMARK_COMPLETE",
        "cases":cases,
        "all_cases_passed":all(x["candidate_valid_for_case"] for x in cases),
        "production_approved":False,
        "premiere_xml_modified":False,"audio_modified":False,
        "cigarette_blur_modified":False,
        "model_detected_cigarette":False,
        "note":"Simulated truth is a development regression, not evidence of real cigarette detection. No tool can pass production solely from this benchmark.",
        "next":"Improve shadow tracking if fast/occlusion/distractor failures, then benchmark labeled real motion with independent detection."
    }
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name("."+target.stem+"."+str(os.getpid())+".tmp")
    try:
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(temp,target)
    finally:
        if temp.is_file():temp.unlink()
    print("=== RG NORFAIR MOTION CHALLENGE RESULT ===",flush=True)
    print(json.dumps({
       "status":report["status"],
       "cases":[{"case":x["case"],"correct":x["correct_position_frames"],
                 "misses":x["missed_visible_frames"],
                 "false_positives":x["false_matches_when_absent"],
                 "case_pass":x["candidate_valid_for_case"]} for x in cases],
       "all_cases_passed":report["all_cases_passed"],
       "production_approved":False,
       "production_modified":False,
       "output":str(target),
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("=== RG NORFAIR MOTION CHALLENGE STOPPED ===",flush=True)
        print(json.dumps({"status":"STOPPED","reason":str(exc),
           "production_modified":False},ensure_ascii=False),flush=True)
        raise SystemExit(2)
