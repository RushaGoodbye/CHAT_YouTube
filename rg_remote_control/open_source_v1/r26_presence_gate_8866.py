#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R26: frame-level object-presence/blur coverage gate for RG Auto Edit.

SHADOW ONLY. Does not render, relabel objects, modify Studio, source, audio
or Premiere XML. A tracker/detector assertion alone never proves blur pixels.
Input is a JSON evidence manifest from an independent detector or reviewer.
Unknown evidence is NOT the same as absence of an object.

A half-open mask interval [start, end) must not cross a scene cut.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

SCHEMA = "RG_R26_OBJECT_PRESENCE_GATE_V1"
OBJECTS = {"bottle", "cigarette", "smoking_hand", "smoking_mouth", "smoke"}
SIDES = {"host", "guest"}
PROTECTED = {"microphone", "cup"}


def _box(values, width, height, name):
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise ValueError(name + ": bbox must have four numbers")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) for v in values):
        raise ValueError(name + ": non-finite bbox")
    x0, y0, x1, y1 = map(float, values)
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(name + ": bbox outside image")
    return (x0, y0, x1, y1)


def _intersection(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _coverage(target, mask):
    return _intersection(target, mask) / (
        (target[2] - target[0]) * (target[3] - target[1]))


def _positive_integer(x, name):
    if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
        raise ValueError(name + " must be positive integer")
    return x


def evaluate(manifest):
    """Return a strictly non-releaseable, auditable review report."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unexpected input schema")
    count = _positive_integer(manifest.get("frame_count"), "frame_count")
    width = _positive_integer(manifest.get("width"), "width")
    height = _positive_integer(manifest.get("height"), "height")
    if count > 1_000_000 or width > 16000 or height > 16000:
        raise ValueError("Unreasonably large manifest")
    min_coverage = float(manifest.get("min_target_coverage", 0.94))
    if not math.isfinite(min_coverage) or not 0.9 <= min_coverage <= 1:
        raise ValueError("min_target_coverage must be 0.9..1")

    cuts = manifest.get("cut_frames", [])
    if not isinstance(cuts, list) or any(
        isinstance(c, bool) or not isinstance(c, int) or
        not (0 < c < count) for c in cuts
    ) or len(set(cuts)) != len(cuts):
        raise ValueError("Invalid cut frame list")
    cuts = sorted(cuts)
    issues = []
    evidence = {}
    required = manifest.get("required_pairs")
    if not isinstance(required, list) or not required:
        raise ValueError("Explicit non-empty required_pairs is mandatory")
    pairs = set()
    for p in required:
        if not isinstance(p, dict) or p.get("participant") not in SIDES or p.get("object") not in OBJECTS:
            raise ValueError("Invalid required pair")
        pairs.add((p["participant"], p["object"]))
    if len(pairs) != len(required):
        raise ValueError("Duplicate required pairs")

    for row in manifest.get("evidence", []):
        if not isinstance(row, dict):
            raise ValueError("Evidence row is not an object")
        f, side, obj = row.get("frame"), row.get("participant"), row.get("object")
        if isinstance(f, bool) or not isinstance(f, int) or not (0 <= f < count):
            raise ValueError("Evidence frame out of bounds")
        if (side, obj) not in pairs:
            raise ValueError("Evidence outside required pairs")
        key = (f, side, obj)
        if key in evidence:
            raise ValueError("Duplicate evidence: " + str(key))
        status = row.get("presence")
        if status not in ("present", "absent", "unknown"):
            raise ValueError("Presence must be present/absent/unknown")
        bbox = row.get("bbox")
        if status == "present":
            bbox = _box(bbox, width, height, "evidence")
            if row.get("semantic_verified") is not True:
                status = "unknown"
        elif bbox is not None:
            raise ValueError("Absent/unknown evidence must not have a bbox")
        if status == "absent" and row.get("semantic_verified") is not True:
            status = "unknown"
        evidence[key] = {"status": status, "bbox": bbox if status == "present" else None}

    # A mask has one verified category and participant, NOT a generic face mask.
    masks_by_key = {}
    masks = manifest.get("masks", [])
    if not isinstance(masks, list):
        raise ValueError("masks must be a list")
    for i, m in enumerate(masks):
        if not isinstance(m, dict):
            raise ValueError("Invalid mask row")
        side, obj = m.get("participant"), m.get("object")
        if (side, obj) not in pairs:
            raise ValueError("Unrecognized mask class or participant")
        start, end = m.get("start"), m.get("end")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)) or not (0 <= start < end <= count):
            raise ValueError("Invalid half-open mask interval")
        box = _box(m.get("bbox"), width, height, "mask")
        for cut in cuts:
            if start < cut < end:
                issues.append({"kind": "MASK_CROSSES_CUT", "frame": cut, "mask_index": i})
        for f in range(start, end):
            masks_by_key.setdefault((f, side, obj), []).append((box, i))

    required_frames = count * len(pairs)
    unknown = missing = false_blur = protected_overlap = 0
    reviewed = covered = 0
    for f in range(count):
        for side, obj in sorted(pairs):
            key = (f, side, obj)
            row = evidence.get(key, {"status": "unknown", "bbox": None})
            mask_boxes = masks_by_key.get(key, [])
            if row["status"] == "unknown":
                unknown += 1
                if mask_boxes:
                    issues.append({"kind": "MASK_WITHOUT_VERIFIED_OBJECT_PRESENCE", "frame": f,
                                   "participant": side, "object": obj})
                continue
            reviewed += 1
            if row["status"] == "absent":
                if mask_boxes:
                    false_blur += 1
                    issues.append({"kind": "MASK_WHEN_OBJECT_ABSENT", "frame": f,
                                   "participant": side, "object": obj})
                continue
            if not any(_coverage(row["bbox"], box) >= min_coverage
                       for box, _ in mask_boxes):
                missing += 1
                issues.append({"kind": "OBJECT_VISIBLE_WITHOUT_SUFFICIENT_MASK", "frame": f,
                               "participant": side, "object": obj})
            else:
                covered += 1

    # Index masks by frame and side: linear in mask frames + protected rows.
    # Never rescan the entire timeline for every microphone/cup observation.
    protected_index = {}
    for (frame, side, _), selections in masks_by_key.items():
        protected_index.setdefault((frame, side), []).extend(selections)
    # Protected regions are checked regardless of tracked category.
    for p in manifest.get("protected_evidence", []):
        f, side, obj = p.get("frame"), p.get("participant"), p.get("object")
        if isinstance(f, bool) or not isinstance(f, int) or not 0 <= f < count:
            raise ValueError("Invalid protected frame")
        if side not in SIDES or obj not in PROTECTED or p.get("semantic_verified") is not True:
            raise ValueError("Unverified protected region")
        box = _box(p.get("bbox"), width, height, "protected")
        for mask, idx in protected_index.get((f, side), []):
            if _coverage(box, mask) > 0.20:
                protected_overlap += 1
                issues.append({"kind": "PROTECTED_MICROPHONE_OR_CUP_OVERLAP",
                               "frame": f, "mask_index": idx, "protected": obj})

    summary = Counter(x["kind"] for x in issues)
    # Never confuse structural coverage with proven pixels or unchanged audio.
    structurally_clean = reviewed == required_frames and not issues
    return {
        "schema": SCHEMA,
        "frame_count": count,
        "required_object_frame_checks": required_frames,
        "semantically_reviewed_object_frames": reviewed,
        "unknown_object_frames": unknown,
        "confirmed_covered_object_frames": covered,
        "visible_object_uncovered_frames": missing,
        "mask_on_confirmed_absence_frames": false_blur,
        "protected_overlap_events": protected_overlap,
        "cuts": cuts,
        "mask_count": len(masks),
        "issues_by_kind": dict(sorted(summary.items())),
        "issues": issues[:300],
        "issue_count": len(issues),
        "issues_truncated": len(issues) > 300,
        "structural_candidate_pass": structurally_clean,
        "video_pixel_qa_pass": False,
        "audio_bit_exact_verified": False,
        "release_ready": False,
        "reason": ("FRAME_EVIDENCE_AND_MASK_GEOMETRY_ONLY_"
                   "REAL_RENDER_PIXEL_AUDIO_QA_REQUIRED"),
        "production_modified": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    source = args.input.resolve()
    dst = args.output.resolve()
    if source == dst or dst.suffix.lower() != ".json":
        raise SystemExit("Refusing to overwrite input or use non-JSON output")
    manifest = json.loads(source.read_text(encoding="utf-8-sig"))
    report = evaluate(manifest)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
        ("frame_count", "required_object_frame_checks", "unknown_object_frames",
         "visible_object_uncovered_frames", "mask_on_confirmed_absence_frames",
         "structural_candidate_pass", "release_ready")}))
    # UNKNOWN and unmasked visible objects are explicit failure, not success.
    return 0 if report["structural_candidate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
