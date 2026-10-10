#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only real Studio smoking markers audit on AlexPC.

All inputs stay untouched. No video decoding, no XML/JSON writes.
Tests the installed bridge against existing real Premiere XMEML and a real
cigarette detection report when available. Synthetic fallback is separately
labeled and never claimed as an actual new dialogue test.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
AFTER_INSTALL=dt.datetime(2026,10,10,11,55,51,tzinfo=dt.timezone.utc).timestamp()
MARK_NAME="RG | ПЕРЕВІРИТИ КУРІННЯ"
SCAN_MAX=8500
FILE_CAP=7_000_000

def valid(name:str):
    return re.match(r"^RG_EDITED_(\d{3,5})(?:_(\d+))?\.xml$",name,re.I)

def walk_bounded():
    # Prioritize recent numbered stream output folders before large app root.
    folders=[]
    for p in APP.iterdir():
        if p.is_dir() and re.fullmatch(r"\d{3,5}",p.name):
            folders.append(p)
    folders.sort(key=lambda p:(p.stat().st_mtime,int(p.name)),reverse=True)
    folders.append(APP)
    files=[]
    visited=0
    for root in folders:
        for entry in root.iterdir():
            visited+=1
            if visited>SCAN_MAX:break
            if entry.is_file() and entry.stat().st_size<=FILE_CAP and (
                valid(entry.name) or entry.name.endswith("_CIGARETTE_BLUR_DETECTIONS.json")
                or entry.name.endswith("_SMOKING_MARKERS.json")
            ):
                files.append(entry)
        if visited>SCAN_MAX:break
    return files,visited

def summary_xml(path):
    data=path.read_text(encoding="utf-8-sig")
    root=ET.fromstring(data.split("<!DOCTYPE xmeml>",1)[1].strip() if "<!DOCTYPE xmeml>" in data else data)
    if root.tag!="xmeml":raise ValueError("Not XMEML")
    seq=root.find("sequence")
    if seq is None:raise ValueError("Missing sequence")
    markers=[]
    for m in seq.findall("marker"):
        name=m.findtext("name") or ""
        if not name.startswith(MARK_NAME):continue
        markers.append({"start":m.findtext("in"),"end":m.findtext("out"),"name":name})
    return {"name":path.name,"size":path.stat().st_size,
            "modified_utc":dt.datetime.fromtimestamp(path.stat().st_mtime,dt.timezone.utc).isoformat(),
            "modified_after_install":bool(path.stat().st_mtime>=AFTER_INSTALL),
            "marker_count":len(markers),"marker_preview":markers[:4],
            "sequence_frames":seq.findtext("duration"),
            "xml_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    assert os.name=="nt" and APP.is_dir(),"AlexPC app required"
    sys.path.insert(0,str(APP))
    from rg_smoking_auto_export_v2 import prepare
    from rg_smoking_uncertainty_timeline_v1 import _roundtrip_check
    listed,count=walk_bounded()
    xmls=sorted([p for p in listed if valid(p.name)],key=lambda p:p.stat().st_mtime,reverse=True)[:28]
    reports=[p for p in listed if p.name.endswith("_CIGARETTE_BLUR_DETECTIONS.json")]
    reports_by_stem={p.name.split("_CIGARETTE_BLUR_DETECTIONS.json")[0]:p for p in reports}
    summaries=[]
    for p in xmls:
        try:summaries.append(summary_xml(p))
        except Exception as e:summaries.append({"name":p.name,"parse_error":str(e)})
    post=[x for x in summaries if x.get("modified_after_install")]
    paired=[]
    for p in xmls[:15]:
        stem=p.stem
        m=valid(p.name)
        stream=m.group(1) if m else None
        det=reports_by_stem.get(stem)
        if not det:continue
        try:
            evidence=json.loads(det.read_text(encoding="utf-8-sig"))
            orig=p.read_text(encoding="utf-8-sig")
            modified,side=prepare(orig,[evidence],stem,stream)
            _roundtrip_check(orig,modified,len(side["markers"]))
            paired.append({"dialogue":stem,
                           "real_xml":True,"real_detection_report":True,
                           "raw_detections":evidence.get("raw_detection_count",0),
                           "confirmed_tracks":evidence.get("confirmed_track_count",0),
                           "rejected_tracks":len(evidence.get("rejected_tracks") or []),
                           "real_report_bridge_marker_count":len(side["markers"]),
                           "report_warnings":side.get("warning_codes"),
                           "audio_video_xml_unchanged":True})
        except Exception as exc:
            paired.append({"dialogue":stem,"real_report_bridge_error":str(exc)[:240]})
    # Independent shadow rehearsal from a REAL existing XML, with fabricated
    # low-confidence timings only; never report this as real detection.
    shadow=None
    for p in xmls:
        m=valid(p.name)
        if m is None or m.group(1)=="886":continue
        try:
            text=p.read_text(encoding="utf-8-sig")
            root=ET.fromstring(text.split("<!DOCTYPE xmeml>",1)[1].strip() if "<!DOCTYPE xmeml>" in text else text)
            c=root.find("./sequence/media/video/track/clipitem")
            if c is None or not c.findtext("name","").startswith(m.group(1)+"."):continue
            a,b=int(c.findtext("in")),int(c.findtext("out"))
            fps=int(root.findtext("./sequence/rate/timebase","30"))
            if b-a<6:continue
            t0=(a+2)/fps
            fabricated={"status":"AMBIGUOUS","passed":False,"raw_detection_count":1,
                        "confirmed_track_count":0,
                        "rejected_tracks":[{"hits":[{"t":t0,"score":0.11}]}]}
            edited,side=prepare(text,[fabricated],p.stem,m.group(1))
            _roundtrip_check(text,edited,len(side["markers"]))
            shadow={"source_dialogue":p.stem,"real_existing_xml":True,
                    "uncertain_detection":"SYNTHETIC_TIME_ONLY_NOT_REAL_AI",
                    "marker_count":len(side["markers"]),
                    "marker_preview":side["markers"][:2],
                    "audio_video_unchanged":True}
            break
        except Exception as exc:
            shadow={"source_dialogue":p.stem,"shadow_error":str(exc)[:240]}
    result={
        "schema":"RG_SMOKING_R1_REAL_DIALOGUE_READONLY_AUDIT_V1",
        "status":"OBSERVATION_ONLY",
        "read_only":True,
        "original_xml_modified":False,
        "source_video_or_audio_modified":False,
        "files_scanned":count,
        "xml_count_bounded":len(xmls),
        "post_install_xml_count":len(post),
        "post_install_marked_xml_count":sum(1 for x in post if x.get("marker_count",0)>0),
        "latest_xmls":summaries[:12],
        "paired_real_xml_and_detection_qa":paired[:10],
        "shadow_with_real_xml":shadow,
        "real_new_dialogue_marker_end_to_end_verified":any(x.get("marker_count",0)>0 for x in post),
        "conclusion":"New-dialogue end-to-end only verified when post-install marked real XML exists",
    }
    print("RG_SMOKING_R1_REAL_DIALOGUE_READONLY_AUDIT")
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
