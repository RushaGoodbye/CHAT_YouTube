#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure XMEML post-export hook: uncertain smoking -> timeline markers.

Not installed in RG Auto Edit Studio. No video/audio changes or network.
Use only after confirmed integration with the installed XML exporter.
"""
from __future__ import annotations
import json
import math
import pathlib
import re
import xml.etree.ElementTree as ET

MARK_NAME = "RG | ПЕРЕВІРИТИ КУРІННЯ"
DEFAULT_REASON = "LOW_CONFIDENCE_SMOKING"
FRAMES_FLAGS = {
    "SMOKE_UNDETECTED", "MOUTH_LANDMARK_UNRELIABLE",
    "CIGARETTE_MASK_EMPTY", "FINGER_CONTACT_UNVERIFIED",
    "IDENTITY_NOT_INDEPENDENTLY_VERIFIED", "SMOKE_MASK_GAPS",
}


def _root(xml: str):
    # Python ElementTree rejects DTD with external entities; keep known xmeml
    # doctype stripped from the source string before parsing.
    x = xml.split("<!DOCTYPE xmeml>", 1)[1].strip() if "<!DOCTYPE xmeml>" in xml else xml
    root = ET.fromstring(x)
    if root.tag != "xmeml" or root.find("sequence") is None:
        raise ValueError("Expected Premiere xmeml sequence")
    return root


def _source_key(name):
    base = pathlib.PurePosixPath(str(name or "").replace("\\", "/")).name
    m = re.search(r"(?<!\d)(\d{3,5})(?!\d)", base)
    return m.group(1) if m else ""


def _clip_mapping(root, stream, fps):
    """Only provable one-to-one media mapping, no reverse/retime guessing."""
    track = root.find("./sequence/media/video/track")
    if track is None:
        return []
    out = []
    for c in track.findall("clipitem"):
        name = c.findtext("name", "")
        if not re.search(r"\.(mp4|mov|mxf|mkv|avi)$", name, re.I):
            continue
        if _source_key(name) != str(stream):
            continue
        try:
            start, end, cin, cout = (
                int(c.findtext(t, "")) for t in ("start", "end", "in", "out")
            )
        except (ValueError, TypeError):
            continue
        if start >= 0 and end > start and cin >= 0 and cout > cin and end - start == cout - cin:
            out.append((cin, cout, start))
    return out


def _span(t0, t1, code, stream, key=None):
    try:
        a = float(t0)
        b = float(t1)
    except (TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (a, b))) or not 0 <= a < b:
        return None
    if key is not None and str(key) != str(stream):
        return None
    return a, b, str(code or DEFAULT_REASON)


def _uncertain_spans(reports, stream, fps):
    result = []
    unlocated = 0
    for rep in reports:
        for w in rep.get("uncertain_spans", []):
            if not isinstance(w, dict):
                continue
            code = "|".join(str(x) for x in w.get("reason_codes", [DEFAULT_REASON]))
            item = _span(w.get("source_start_sec"), w.get("source_end_sec"),
                         code, stream, w.get("source_key"))
            if item: result.append(item)
        for tr in rep.get("rejected_tracks", []):
            for h in tr.get("hits", []):
                try: ts = float(h["t"])
                except (ValueError, TypeError, KeyError):
                    unlocated += 1
                    continue
                item = _span(max(0,ts-.25), ts+.35, "LOW_CONFIDENCE_CIGARETTE", stream)
                if item: result.append(item)
        for frame in rep.get("frames", []):
            if not isinstance(frame,dict):
                continue
            if "source_frame" in frame:
                codes = FRAMES_FLAGS.intersection(frame.get("flags") or [])
                if codes:
                    i = frame["source_frame"]
                    item = _span(float(i)/fps, (float(i)+1)/fps,
                                 "|".join(sorted(codes)), stream)
                    if item: result.append(item)
            elif frame.get("boxes") and "t" in frame:
                try: weak=any(float(b.get("score",1)) < .34
                              for b in frame["boxes"] if isinstance(b,dict))
                except (ValueError,TypeError):
                    weak=False
                if weak:
                    ts=float(frame["t"])
                    item=_span(max(0,ts-.15),ts+.25,"WEAK_CIGARETTE",stream)
                    if item:result.append(item)
        if rep.get("unconfirmed_detection_count") and not rep.get("rejected_tracks"):
            unlocated += int(rep["unconfirmed_detection_count"])
    return result, unlocated


def mark_xml(xml: str, reports: list[dict], stream: str, dialogue: str):
    root = _root(xml)
    seq = root.find("sequence")
    fpsnode = seq.find("./rate/timebase")
    if fpsnode is None or not fpsnode.text:
        raise ValueError("Missing timebase")
    fps = int(fpsnode.text)
    if not 1 <= fps <= 240:
        raise ValueError("Unsupported timebase")
    limit = int(seq.findtext("duration", "-1"))
    if limit < 1:
        raise ValueError("Invalid timeline duration")
    mapping = _clip_mapping(root, stream, fps)
    spans, unlocated = _uncertain_spans(reports, stream, fps)
    markers = []
    for start, end, reason in spans:
        for cin, cout, tl0 in mapping:
            ia = max(int(round(start * fps)), cin)
            ib = min(int(round(end * fps)), cout)
            if ib <= ia: continue
            a = tl0 + (ia - cin)
            b = tl0 + (ib - cin)
            if a < 0 or b > limit:
                raise ValueError("Marker escapes final timeline")
            markers.append((a, b, reason))
    markers = sorted(set(markers))
    # Coalesce contiguous frame markers, but do not combine across a video cut.
    merged = []
    for a,b,reason in markers:
        if merged and merged[-1][1] == a and merged[-1][2] == reason:
            merged[-1] = (merged[-1][0],b,reason)
        else:
            merged.append((a,b,reason))
    for old in list(seq.findall("marker")):
        if (old.findtext("name") or "").startswith(MARK_NAME):
            seq.remove(old)
    for i,(a,b,reason) in enumerate(merged,1):
        m=ET.SubElement(seq,"marker")
        ET.SubElement(m,"name").text=f"{MARK_NAME} #{i:02d}"
        ET.SubElement(m,"comment").text=f"AI: перевірити куріння. Причина: {reason}"
        ET.SubElement(m,"in").text=str(a)
        ET.SubElement(m,"out").text=str(b)
    marked='<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root,encoding="unicode")
    after=_root(marked).find("sequence")
    before=_root(xml).find("sequence")
    for path in ("media/video","media/audio"):
        x,y=before.find(path),after.find(path)
        if (x is None)!=(y is None) or (x is not None and ET.tostring(x)!=ET.tostring(y)):
            raise RuntimeError("Forbidden media subtree change")
    side = {"schema":"RG_SMOKING_TIMELINE_MARKER_HOOK_V1",
            "dialogue":str(dialogue), "stream":str(stream),
            "fps":fps, "markers":[{"start_frame":a,"end_frame":b,
                                   "start_sec":round(a/fps,5),"end_sec":round(b/fps,5),
                                   "reason":reason} for a,b,reason in merged],
            "warning_codes":([] if not unlocated else ["AI_EVENTS_WITHOUT_SOURCE_TIMECODE"])
                + ([] if mapping or not spans else ["NO_RETAINED_SOURCE_CLIP_MAP"]),
            "low_confidence_blocks_dialogue":False,
            "source_xml_modified":False,
            "production_studio_installed":False}
    return marked,side


def selftest():
    raw=('<xmeml><sequence><duration>100</duration><rate><timebase>30</timebase></rate>'
         '<media><video><track><clipitem><name>892.mp4</name><start>0</start>'
         '<end>60</end><in>360</in><out>420</out></clipitem></track></video>'
         '<audio><track><clipitem><name>audio</name></clipitem></track></audio></media>'
         '</sequence></xmeml>')
    evidence=[{"uncertain_spans":[{"source_start_sec":12.3,"source_end_sec":12.6,
                                     "reason_codes":["SMOKE_UNCERTAIN"]}]}]
    result,s=mark_xml(raw,evidence,"892","892_1")
    assert s["markers"][0]["start_frame"]==9
    assert mark_xml(result,evidence,"892","892_1")[0].count("<marker>")==1
    assert not s["low_confidence_blocks_dialogue"]
    print("RG_SMOKING_MARKER_HOOK_SELFTEST_PASS")


if __name__ == "__main__":
    selftest()
