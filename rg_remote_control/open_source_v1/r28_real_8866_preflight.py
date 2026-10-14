#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R28 read-only preflight: timeline-to-source mapping for 886_6.

No video/audio writes, no production XML changes, no installation.
Only considers a V1 cut a safe original-886 source mapping when the FCP7
duration and source in/out are exactly equal (speed=1x). Unknowns are explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

SCHEMA = "RG_R28_8866_REAL_SOURCE_PREFLIGHT_V1"
ROOT = Path(r"F:\RG_AUTO_EDIT")
APP = ROOT / "RG Auto Edit App"
DATA = ROOT / "RG Auto Edit Data"
SOURCE = Path(r"\\Desktop-v7gg0en\record\886.mp4")
XML_CANDIDATES = (APP / "RG_EDITED_886_6.xml", DATA / "RG_EDITED_886_6.xml")
FFMPEG = Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE")
TIMELINE_FRAMES = (60, 100, 396, 1560, 2640, 3766, 5280)

def as_int(el, tag):
    try:
        v = el.findtext(tag)
        if v is None: return None
        return int(v)
    except (TypeError, ValueError):
        return None

def parse_timeline(xml_bytes):
    root=ET.fromstring(xml_bytes)
    seq=root.find(".//sequence")
    if seq is None:
        raise ValueError("Premiere/FCP7 XML sequence missing")
    seq_dur = as_int(seq, "duration")
    tb = as_int(seq, "./rate/timebase")
    tracks = seq.findall("./media/video/track")
    if not tracks:
        raise ValueError("Sequence has no video tracks")
    rows=[]
    for track_idx, track in enumerate(tracks, start=1):
        for ci in track.findall("clipitem"):
            start,end,inn,out=(as_int(ci,x) for x in ("start","end","in","out"))
            if None in (start,end,inn,out) or end <= start or out <= inn:
                continue
            name = ci.findtext("name") or ci.findtext("./file/name") or ""
            fileid = (ci.find("file").attrib.get("id","") if ci.find("file") is not None else "")
            direct_source = "886.mp4" in name.lower() or "886.mp4" in fileid.lower()
            if not direct_source and track_idx==1 and ci.find("file") is not None:
                # Referenced FCP7 file elements may contain ID only; do not
                # claim identity until the file metadata can be resolved.
                ref=ci.find("file")
                fid=ref.get("id")
                if fid:
                    for item in root.findall(".//file"):
                        if item.get("id")==fid:
                            fname=item.findtext("name","") + " " + item.findtext("pathurl","")
                            if "886.mp4" in fname.lower():
                                direct_source=True
                                break
            rows.append({
                "track":track_idx, "start":start, "end":end,
                "source_in":inn, "source_out":out,
                "source_886":direct_source,
                "simple_1x_mapping":(end-start)==(out-inn),
            })
    if not rows:
        raise ValueError("No usable clipitem cuts")
    samples=[]
    for t in TIMELINE_FRAMES:
        covering=[c for c in rows if c["track"]==1 and c["start"]<=t<c["end"]]
        if len(covering)==1 and covering[0]["source_886"] and covering[0]["simple_1x_mapping"]:
            c=covering[0]
            samples.append({"timeline_frame":t,
                            "source_frame":c["source_in"]+(t-c["start"]),
                            "mapped":True})
        else:
            samples.append({"timeline_frame":t, "mapped":False,
                            "reason":"NO_UNAMBIGUOUS_V1_SOURCE_1X_MAP"})
    v1=sorted((r for r in rows if r["track"]==1),key=lambda x:x["start"])
    discrepancies=[{
        "timeline_start":c["start"],"timeline_end":c["end"],
        "timeline_frames":c["end"]-c["start"],
        "source_frames":c["source_out"]-c["source_in"],
        "duration_delta":(c["source_out"]-c["source_in"])-(c["end"]-c["start"])
    } for c in v1 if c["source_886"] and not c["simple_1x_mapping"]]
    v1_cut_frames=sorted(set(c["start"] for c in v1 if 0<c["start"]<seq_dur))
    return {
        "v1_cut_frames":v1_cut_frames,
        "v1_non_1x_count":len(discrepancies),
        "v1_non_1x_discrepancies":discrepancies,
        "sequence_duration_frames":seq_dur,
        "timebase":tb,
        "video_track_count":len(tracks),
        "all_cut_count":len(rows),
        "v1_clip_count":sum(c["track"]==1 for c in rows),
        "v1_direct_source_886_clip_count":sum(c["track"]==1 and c["source_886"] for c in rows),
        "v1_1x_source_map_count":sum(c["track"]==1 and c["source_886"] and c["simple_1x_mapping"] for c in rows),
        "target_frame_samples":samples,
        "exact_5842_30fps_sequence":seq_dur==5842 and tb==30,
    }

def probe_one(ffmpeg, source, source_frame, rate=30):
    t=source_frame/rate
    cmd=[str(ffmpeg),"-nostdin","-hide_banner","-loglevel","error",
         "-ss",f"{t:.4f}","-i",str(source),"-frames:v","1","-an","-sn",
         "-f","null","-"]
    try:
        p=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                         text=True,encoding="utf-8",errors="replace",timeout=45,
                         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return {"decoded":p.returncode==0,"timed_out":False}
    except subprocess.TimeoutExpired:
        return {"decoded":False,"timed_out":True}

def run(xml_content, source_exists, ffmpeg_exists, decode=None):
    mapping=parse_timeline(xml_content)
    result = {
        "schema":SCHEMA,
        "read_only":True,
        "original_video_modified":False,
        "original_xml_modified":False,
        "studio_modified":False,
        "source_accessible":bool(source_exists),
        "ffmpeg_available":bool(ffmpeg_exists),
        "mapping":mapping,
        "sample_decode":[],
        "real_visual_qa_completed":False,
        "release_ready":False,
    }
    if decode is not None:
        for row in mapping["target_frame_samples"]:
            if row["mapped"] and len(result["sample_decode"])<3:
                item=decode(row["source_frame"])
                result["sample_decode"].append({"timeline_frame":row["timeline_frame"],
                                               "source_frame":row["source_frame"],
                                               **item})
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--decode-three", action="store_true")
    opts=ap.parse_args()
    if opts.selftest:
        # Use a tiny entirely synthetic FCP7 sequence, no media dependencies.
        fake = (b'<xmeml><sequence><duration>5842</duration><rate><timebase>30</timebase></rate>'
                b'<media><video><track><clipitem><name>886.mp4</name><start>0</start>'
                b'<end>5842</end><in>1000</in><out>6842</out><file id="file-1" />'
                b'</clipitem></track></video></media></sequence></xmeml>')
        r = run(fake,False,False)
        assert r["mapping"]["target_frame_samples"][0]["source_frame"]==1060
        assert r["mapping"]["exact_5842_30fps_sequence"] is True
        assert r["release_ready"] is False
        print("RG_R28_PREVIEW_FCP7_SELFTEST: PASS")
        return
    paths=[x for x in XML_CANDIDATES if x.is_file()]
    if not paths:
        raise SystemExit("Expected dialogue XML not found in designated App/Data paths")
    xml_file=paths[0]
    raw=xml_file.read_bytes()
    ffmpeg_exists=FFMPEG.is_file()
    source_exists=SOURCE.is_file()
    decode=(lambda f:probe_one(FFMPEG,SOURCE,f)) if opts.decode_three and source_exists and ffmpeg_exists else None
    r=run(raw,source_exists,ffmpeg_exists,decode)
    r["xml_sha256"]=hashlib.sha256(raw).hexdigest()
    r["source_size_expected_match"]=(SOURCE.stat().st_size==15333867413) if source_exists else False
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if not r["mapping"]["exact_5842_30fps_sequence"]:
        raise SystemExit("NOT_886_6_EXACT_SEQUENCE")
    if not any(x["mapped"] for x in r["mapping"]["target_frame_samples"]):
        raise SystemExit("CANNOT_MAP_DIALOGUE_TO_SOURCE")
    if opts.decode_three and (not r["sample_decode"] or not all(x["decoded"] for x in r["sample_decode"])):
        raise SystemExit("FRAME_DECODING_QA_FAILED")

if __name__=="__main__":
    main()
