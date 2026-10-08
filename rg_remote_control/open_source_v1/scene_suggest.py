#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PySceneDetect shadow-mode integration for RG Auto Edit Studio.

Never cuts media, rewrites XML, declares a dialogue ended, touches original audio,
or changes the mandatory cigarette blur pipeline.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

VERSION = "RG_OSS_SCENE_SHADOW_V1"
DEFAULT_ROOT = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
MAX_DURATION_SEC = 600.0

def validate_window(start_sec: float, duration_sec: float) -> tuple[float,float]:
    start=float(start_sec)
    duration=float(duration_sec)
    if not (start >= 0 and 0 < duration <= MAX_DURATION_SEC):
        raise ValueError(f"Only positive windows up to {MAX_DURATION_SEC:g} seconds are supported")
    if not (start < 360000 and start+duration <= 360000):
        raise ValueError("Invalid or excessive stream time range")
    return start,start+duration

def as_sec(frame_timecode: Any) -> float:
    val=float(frame_timecode.get_seconds())
    if val < 0 or val != val or val == float("inf"):
        raise ValueError("Invalid timecode from scene detector")
    return round(val,5)

def suggest_cuts(scenes, window_start: float, window_end: float) -> list[dict]:
    """Evidence only: no cut command, no irreversible dialogue-end classification."""
    candidates = []
    for i,(beg,end) in enumerate(scenes):
        a=as_sec(beg);b=as_sec(end)
        if not (window_start-0.1 <= a < b <= window_end+0.1):
            raise ValueError(f"Scene time outside requested video window: {a}..{b}")
        if i > 0 and a > window_start:
            candidates.append({
                "at_source_sec":a,
                "kind":"SCENE_CHANGE_CANDIDATE",
                "confidence":"UNASSESSED",
                "dialogue_end":False,
                "requires":"CLOCK_BOUNDARY_OR_HOST_GUEST_TRANSITION_CONFIRMATION"
            })
    return candidates

def inspect_module():
    import importlib.metadata as metadata
    try:
        installed=metadata.version("scenedetect")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "PySceneDetect not installed in isolated OSS runtime; do not install it in production environment"
        ) from exc
    parts=installed.split(".")
    if len(parts)<2 or parts[0]!="0" or parts[1]!="7":
        raise RuntimeError(f"Unsupported PySceneDetect version {installed}; require 0.7.x")
    from scenedetect import detect, AdaptiveDetector
    return installed,detect,AdaptiveDetector

def analyze(video: Path, start_sec: float, duration_sec: float, *,
            detector_fn=None, detector_class=None) -> dict:
    lo,hi=validate_window(start_sec,duration_sec)
    if not video.is_file():
        raise FileNotFoundError(f"Video missing: {video}")
    if detector_fn is None or detector_class is None:
        version, detector_fn, detector_class = inspect_module()
    else:
        version="TEST_DOUBLE"
    scenes=detector_fn(
        str(video),detector_class(),start_time=lo,end_time=hi,
        start_in_scene=True,show_progress=False
    )
    candidates=suggest_cuts(scenes,lo,hi)
    return {
        "schema":VERSION,"status":"SHADOW_PASS",
        "component":"PySceneDetect","component_version":version,
        "stream_video":str(video),
        "window":{"start_sec":lo,"end_sec":hi,"duration_sec":duration_sec},
        "scene_count":len(scenes),"candidate_count":len(candidates),
        "candidates":candidates,
        "production_applied":False,"dialogue_end_auto_applied":False,
        "xml_modified":False,"source_audio_modified":False,
        "cigarette_blur_modified":False,
        "safety":"CANDIDATES_ONLY_FAIL_CLOSED_PRODUCTION_UNCHANGED"
    }

def save_shadow(result: dict, output: Path, root: Path):
    root=root.resolve()
    output=output.resolve()
    if root not in output.parents or output.suffix.lower() != ".json":
        raise ValueError("Output must be a JSON file within isolated OSS shadow folder")
    output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_name(f".{output.stem}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,output)
    finally:
        if tmp.exists():tmp.unlink()

def main(argv=None):
    ap=argparse.ArgumentParser(description="RG Auto Edit scene hints, SHADOW ONLY")
    ap.add_argument("--video",type=Path,required=True)
    ap.add_argument("--start-sec",type=float,required=True)
    ap.add_argument("--duration-sec",type=float,default=120.0)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args(argv)
    start,end=validate_window(args.start_sec,args.duration_sec)
    root=Path(os.environ.get("RG_OSS_SHADOW_ROOT") or DEFAULT_ROOT)
    video=args.video.resolve(strict=True)
    result=analyze(video,start,args.duration_sec)
    out=args.output or root / f"scene_{video.stem}_{int(start*1000)}_{int(end*1000)}.json"
    save_shadow(result,out,root)
    print(json.dumps({"status":"SHADOW_PASS","output":str(out),
       "candidate_count":result["candidate_count"],
       "production_applied":False},ensure_ascii=False))

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status":"SHADOW_ERROR","reason":str(exc),
            "production_applied":False},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(2)
