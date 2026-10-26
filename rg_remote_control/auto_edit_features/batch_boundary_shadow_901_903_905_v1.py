#!/usr/bin/env python3
"""RG Auto Edit: single safe shadow audit of 901/905 overlaps and 903 held dialogue QA.

Read only: NO media, Premiere XML, UI queue, QA, model or cache mutations.
The JSON output is engineering evidence, NEVER an approval for export or auto-trim.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
MAX_XML_BYTES = 50_000_000
EXPECTED_OVERLAPS = {
    "901": {(4, 5): 4843, (5, 6): 3883},
    "905": {(1, 2): 201},
}
TARGETS = ("901", "903", "905")

def read_json(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Missing evidence: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Malformed evidence: {path.name}")
    return value

def positive_int(value, label):
    try:
        n = int(value)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Invalid {label}") from exc
    if n <= 0:
        raise RuntimeError(f"Nonpositive {label}")
    return n

def analyze_interval_report(report: dict, expected: dict) -> dict:
    """Verify reported source overlaps against independently stored source ranges."""
    rows = report.get("dialogues")
    if report.get("passed") is not False or not isinstance(rows, list):
        raise RuntimeError("Expected failed boundary report with dialogue rows")
    spans = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Invalid boundary dialogue entry")
        idx = positive_int(row.get("dialogue"), "dialogue index")
        a = int(row.get("source_in"))
        b = int(row.get("source_out"))
        if b <= a or idx in spans:
            raise RuntimeError("Invalid or duplicate source ranges")
        spans[idx] = (a, b)
    issues = report.get("issues")
    if not isinstance(issues, list):
        raise RuntimeError("Missing boundary issues")
    actual = {}
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("code") != "NEIGHBOUR_XML_SOURCE_OVERLAP":
            raise RuntimeError("Unexpected boundary issue code")
        pair = (positive_int(issue.get("left"), "left"), positive_int(issue.get("right"), "right"))
        if pair in actual or pair[0] not in spans or pair[1] not in spans:
            raise RuntimeError("Duplicate or unknown neighbour issue")
        expected_count = max(0, min(spans[pair[0]][1], spans[pair[1]][1]) -
                             max(spans[pair[0]][0], spans[pair[1]][0]))
        count = positive_int(issue.get("frames"), "overlap frames")
        if count != expected_count:
            raise RuntimeError(f"Report contradicts source intervals: {pair}")
        actual[pair] = count
    if actual != expected:
        raise RuntimeError(f"Source overlap evidence differs from controlled set: {actual}")
    candidates = []
    for (left, right), frames in sorted(actual.items()):
        a, b = spans[left], spans[right]
        candidates.append({
            "neighbours": [left, right],
            "overlap_frames": frames,
            "shared_source_frame_interval": [max(a[0], b[0]), min(a[1], b[1])],
            "case": "LARGE_OVERLAP_REQUIRES_IDENTITY_BOUNDARY_RECONSTRUCTION"
                    if frames > 500 else "SMALL_OVERLAP_REQUIRES_SPEECH_AND_VISUAL_PROOF",
            "may_auto_trim": False,
        })
    return {"verified": True, "source_intervals": {str(k): list(v) for k, v in sorted(spans.items())},
            "overlaps": candidates}

def xml_summary(xml: Path) -> dict:
    """Structural/track metadata only; no source path strings or media contents."""
    if not xml.is_file() or xml.stat().st_size <= 0 or xml.stat().st_size > MAX_XML_BYTES:
        raise RuntimeError("Expected existing bounded Premiere XML")
    root = ET.parse(xml).getroot()
    seq = root.find(".//sequence")
    if seq is None:
        raise RuntimeError("Missing Premiere sequence")
    rate = seq.find("./rate/timebase")
    try:
        fps = int(rate.text) if rate is not None and rate.text else None
    except ValueError:
        fps = None
    def tracks(kind):
        return seq.findall(f"./media/{kind}/track")
    def clips(kind):
        return [clip for tr in tracks(kind) for clip in tr.findall("clipitem")]
    def range_of(items):
        source = []
        for clip in items:
            try:
                beg, end = int(clip.findtext("in")), int(clip.findtext("out"))
                if end > beg:
                    source.append((beg, end))
            except (TypeError, ValueError):
                pass
        return {"source_clip_count": len(source),
                "source_min_frame": min((a for a, _ in source), default=None),
                "source_max_frame": max((b for _, b in source), default=None)}
    video, audio = clips("video"), clips("audio")
    if not video or not audio:
        raise RuntimeError("Premiere sequence missing audio or video clipitems")
    return {"filename": xml.name, "fps_timebase": fps, "video_tracks": len(tracks("video")),
            "audio_tracks": len(tracks("audio")), "video_clips": len(video),
            "audio_clips": len(audio), "video": range_of(video), "audio": range_of(audio)}

def manifest_files(app: Path, stream: str, manifest: dict) -> list[Path]:
    if str(manifest.get("stream")) != stream:
        raise RuntimeError("Manifest stream mismatch")
    rows = manifest.get("outputs")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("No manifest outputs")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Bad manifest entry")
        named = str(row.get("premiere_xml") or "").strip()
        basename = Path(named.replace("\\", "/")).name
        if not re.fullmatch(r"RG_EDITED_"+stream+r"(?:_[1-9]\d*)?(?:_R[1-9]\d*)?\.xml", basename, re.I):
            raise RuntimeError("Unexpected Premiere XML filename")
        path = app / stream / basename
        if not path.is_file():
            raise RuntimeError(f"Primary XML missing: {basename}")
        out.append(path)
    if len({p.name.casefold() for p in out}) != len(out):
        raise RuntimeError("Duplicate primary XML")
    return out

def shadow(app: Path = APP) -> dict:
    result = {"schema": "RG_AUTO_EDIT_BATCH_BOUNDARY_SHADOW_V1", "read_only": True,
              "media_writes": 0, "xml_writes": 0, "qa_writes": 0,
              "automated_approval": False, "streams": {}}
    for stream in TARGETS:
        manifest = read_json(app / f"RG_EDITED_{stream}_MULTI_DIALOGUE.json")
        qa = read_json(app / stream / "RG_POSTRUN_QA.json")
        if str(qa.get("stream")) != stream:
            raise RuntimeError("QA stream mismatch")
        paths = manifest_files(app, stream, manifest)
        data = {"manifest_status": manifest.get("status"), "xml_count": len(paths),
                "postrun_passed": qa.get("passed"), "xml": [xml_summary(x) for x in paths]}
        if stream in EXPECTED_OVERLAPS:
            report = read_json(app / stream / "RG_BOUNDARY_QA_V51.json")
            if manifest.get("status") != "DIALOGUES_COMPLETE" or qa.get("passed") is not False:
                raise RuntimeError("Unexpected overlap review status")
            data["boundary"] = analyze_interval_report(report, EXPECTED_OVERLAPS[stream])
        else:
            held = manifest.get("review_holds")
            if (manifest.get("status") != "PARTIAL_REVIEW" or len(paths) != 4
                or manifest.get("dialogue_count") != 6 or not isinstance(held, list)):
                raise RuntimeError("903 partial dialogue evidence changed")
            ids = {positive_int(x.get("index"), "hold index") for x in held}
            if ids != {2, 5} or len(held) != 2:
                raise RuntimeError("903 held dialogue set changed")
            data["held_dialogues"] = sorted(ids)
            data["may_auto_approve_held"] = False
        result["streams"][stream] = data
    return result

if __name__ == "__main__":
    print("RG_BATCH_BOUNDARY_SHADOW|" + json.dumps(shadow(), ensure_ascii=False), flush=True)
