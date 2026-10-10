#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real 904_5 Audalign local consensus shadow probe. Zero production writes.

Uses saved actual Audalign anchor evidence. Never changes Studio, cache, XML,
media, quarantine or checkpoint. Temp audio windows only on F: and deleted.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
AUDIT=APP/"RG_EDITED_904_5_audio_source_audit.json"
VIDEO=Path(r"\\Desktop-v7gg0en\record\904.mp4")
AUDIO=Path(r"\\Desktop-v7gg0en\record\sound\904.mp3")

def find_ffmpeg():
    xs=[shutil.which("ffmpeg"),
        r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe",
        r"F:\RG_AUTO_EDIT\RG Auto Edit App\tools\ffmpeg.exe",
        r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\ffmpeg.exe"]
    for p in xs:
        if p and Path(p).is_file():
            return str(p)
    return None

def main():
    assert os.name=="nt"
    assert APP.is_dir() and VIDEO.is_file() and AUDIO.is_file() and AUDIT.is_file()
    a=json.loads(AUDIT.read_text(encoding="utf-8-sig"))
    d=a["dialogue_anchor"]
    v0=float(d["dialogue_start_sec"]);v1=float(d["dialogue_end_sec"])
    allpts=[p for p in a["robust_inliers"] if p.get("status")=="MATCH" and
            float(p.get("correlation_confidence",0))>=.9]
    first=[p for p in allpts if float(p["video_sec"])<6000]
    last=[p for p in allpts if float(p["video_sec"])>=6800]
    assert len(first)>=4 and len(last)>=4
    def m(ps):return statistics.median(float(x["offset_sec"]) for x in ps)
    assert 10 < m(last)-m(first) < 300
    assert max(float(x["offset_sec"]) for x in last)-min(float(x["offset_sec"]) for x in last)<.2
    assert min(float(x["video_sec"]) for x in last)-30<v0
    assert max(float(x["video_sec"]) for x in last)+30>v1
    clean_duration=float(a.get("clean_audio_duration_sec_info_only",12000))
    if v1+m(last)>clean_duration: raise RuntimeError("audio duration not verified")
    ffmpeg=find_ffmpeg()
    if not ffmpeg:
        print(json.dumps({"status":"BLOCKED_FFMPEG_NOT_FOUND","source_read_only":True}))
        raise SystemExit(3)
    sys.path.insert(0,str(APP))
    from rg_oss_sync import refine_dialogue_sync
    chosen_offset=float(m(last))
    base={
       "offset_sec":chosen_offset,"speed_ratio":1.0,
       "confidence":"low", # cannot be elevated before independent local proof
       "piecewise_audio_sync":{"enabled":False,"mode":"linear_fallback"},
       "audalign_epoch_shadow_candidate":True
    }
    scratch=DATA/"oss_shadow"
    scratch.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rg904_audalign_epoch_shadow_",dir=str(scratch)) as td:
        t=time.time()
        result=refine_dialogue_sync(ffmpeg,VIDEO,AUDIO,base,
                      {"start":v0,"end":v1},td)
        dur=time.time()-t
    anchor=result.get("dialogue_anchor") or {}
    summary={
        "schema":"RG_904_5_AUDALIGN_EPOCH_SHADOW_V1",
        "status":"LOCAL_CONSENSUS_PASS" if anchor.get("accepted") else "LOCAL_CONSENSUS_FAIL",
        "source_read_only":True,"production_audio_modified":False,
        "production_video_modified":False,"production_xml_modified":False,
        "premiere_checkpoint_unchanged":True,
        "dialogue_video_interval":[v0,v1],
        "old_global_offset_sec":a["sync_offset_sec"],
        "late_epoch_proposed_offset_sec":chosen_offset,
        "early_epoch_median_offset_sec":m(first),
        "epoch_offset_jump_sec":m(last)-m(first),
        "local_anchor_accepted":bool(anchor.get("accepted")),
        "local_anchor_reason":anchor.get("reason"),
        "good_anchor_count":anchor.get("good_anchor_count"),
        "consensus_anchor_count":anchor.get("consensus_anchor_count"),
        "applied_correction_sec":anchor.get("applied_correction_sec"),
        "final_offset_sec":result.get("offset_sec"),
        "final_confidence":result.get("confidence"),
        "local_anchor_details":anchor.get("anchors"),
        "runtime_sec":round(dur,2)
    }
    print("RG_904_AUDALIGN_EPOCH_SHADOW_RESULT")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if not anchor.get("accepted"):
        raise SystemExit(5)

if __name__=="__main__":main()
