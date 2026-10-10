#!/usr/bin/env python3
"""Audit existing RG_892_THREEZONE_FUSION_SHADOW_V1.zip without running a model.

This is strictly diagnostics. No retouching of the Studio, source video or Premiere XML.
Any geometric match is a proxy, not independently verified cigarette/finger identity.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
from pathlib import Path
import zipfile

COUNT = 60
ROI = (1000, 240, 1740, 850)
SCHEMA = "RG_892_THREEZONE_CIGAR_HAND_MOUTH_SHADOW_V1"
YU_SCHEMA = "RG_YUNET_892_REAL_MOUTH_LANDMARKS_SHADOW_V1"
SRC_SHA = "bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"


def load_report(z, expected):
    if z.testzip() is not None:
        raise ValueError("ZIP CRC failure")
    d = json.loads(z.read("report.json"))
    if d.get("schema") != expected:
        raise ValueError("Wrong report schema")
    if len(d.get("frames", [])) != COUNT:
        raise ValueError("Expected exactly 60 frame records")
    if d.get("production_release_allowed") is not False:
        raise ValueError("Production release must be explicitly blocked")
    return d


def audit(threezone, yunet):
    import cv2
    import numpy as np

    issues = []
    rows = []
    with zipfile.ZipFile(threezone) as z, zipfile.ZipFile(yunet) as y:
        result = load_report(z, SCHEMA)
        guide = load_report(y, YU_SCHEMA)
        if result.get("source_sha256") != SRC_SHA or result.get("frames_total") != COUNT:
            raise ValueError("Threezone source identity/size mismatch")
        if guide.get("source_frame_offset") != 360:
            raise ValueError("YuNet frame offset mismatch")
        if (result.get("source_frames") != [360, 419]
                or result.get("studio_modified") is not False
                or result.get("quarantine_886_5_unchanged") is not True):
            raise ValueError("Safety or source-frame contract violated")
        if result.get("smoke_detector_verified") is not False:
            raise ValueError("Unexpected smoke detector assertion")

        files = set(z.namelist())
        required = {"THREEZONE_892_UNAPPROVED_2S_NO_AUDIO.mp4", "metrics.csv"}
        required |= {f"cigar_masks/{i:02d}.png" for i in range(COUNT)}
        required |= {f"hand_masks/{i:02d}.png" for i in range(COUNT)}
        missing = sorted(required - files)
        if missing:
            raise ValueError(f"Missing required outputs: {missing[:8]}")

        first = None
        prev_cigar_area = None
        prev_center = None
        for i in range(COUNT):
            f = result["frames"][i]
            ref = guide["frames"][i]
            if f.get("source_frame") != i + 360 or ref.get("frame_index") != i:
                raise ValueError(f"Frame index mismatch at {i}")

            def mask(folder):
                data = np.frombuffer(z.read(f"{folder}/{i:02d}.png"), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
                if image is None or image.shape != (610, 740):
                    raise ValueError(f"Invalid {folder} PNG frame {i}")
                return image > 127

            c = mask("cigar_masks")
            h = mask("hand_masks")
            c_area = int(c.sum())
            h_area = int(h.sum())
            warnings = []
            if not c_area:
                warnings.append("EMPTY_CIGARETTE")
            if c_area and not (10 <= c_area <= 8000):
                warnings.append("CIGARETTE_AREA_SUSPECT")
            if c_area > int(f.get("cigar_pixels", -1)):
                raise ValueError(f"Cigarette ROI area exceeds full-mask area at {i}")
            if h_area > int(f.get("hand_pixels", -1)):
                raise ValueError(f"Hand ROI area exceeds full-mask area at {i}")
            if h_area == 0 or h_area > 150000:
                warnings.append("HAND_AREA_SUSPECT")
            if prev_cigar_area and c_area:
                ratio = c_area / prev_cigar_area
                if not (0.35 <= ratio <= 2.8):
                    warnings.append("CIGARETTE_AREA_JUMP")
            if c_area:
                yy, xx = np.nonzero(c)
                center = (float(xx.mean() + ROI[0]), float(yy.mean() + ROI[1]))
                older = ref.get("cigarette_sam2_centroid_xy")
                if older is None or len(older) != 2:
                    raise ValueError(f"Missing reference cigarette centroid at {i}")
                deviation = math.dist(center, older)
                if deviation > 65:
                    warnings.append("CIGARETTE_TRACK_DISAGREES_WITH_REFERENCE")
                if prev_center is not None and math.dist(center, prev_center) > 75:
                    warnings.append("CIGARETTE_CENTER_JUMP")
                prev_center = center
            else:
                center = None
                deviation = None
            dist_to_mouth = float(ref.get("distance_mouth_to_sam2_centroid_px", 1e6))
            if int(f.get("mouth_guide_pixels", 0)) and dist_to_mouth > 110:
                warnings.append("MOUTH_BLUR_WHILE_CIGARETTE_FAR")
            if int(f.get("hand_contact_candidate_pixels", 0)) > h_area:
                raise ValueError(f"Hand-contact pixels exceed hand mask at {i}")
            if int(f.get("union_pixels", 0)) < 0:
                raise ValueError(f"Negative union area at {i}")
            if f.get("automatic_release_allowed") is not False:
                raise ValueError(f"Release enabled at {i}")
            if f.get("flags"):
                warnings.extend(str(w) for w in f["flags"])
            prev_cigar_area = c_area or prev_cigar_area
            row = {
                "frame": i + 360,
                "cigarette_roi_pixels": c_area,
                "hand_roi_pixels": h_area,
                "cigarette_reference_deviation_px": (
                    round(deviation, 2) if deviation is not None else None
                ),
                "mouth_guide_pixels": f.get("mouth_guide_pixels", 0),
                "old_cigarette_to_mouth_distance_px": round(dist_to_mouth, 2),
                "warnings": sorted(set(warnings)),
            }
            rows.append(row)
            if first is None:
                first = row

    counts = {}
    for row in rows:
        for flag in row["warnings"]:
            counts[flag] = counts.get(flag, 0) + 1
    return {
        "schema": "RG_892_THREEZONE_OUTPUT_AUDIT_V1",
        "status": "MANUAL_VISUAL_QA_REQUIRED",
        "total_frames_checked": COUNT,
        "cigarette_empty_frames": sum(row["cigarette_roi_pixels"] == 0 for row in rows),
        "frames_with_mouth_guide": sum(bool(row["mouth_guide_pixels"]) for row in rows),
        "geometric_warning_counts": dict(sorted(counts.items())),
        "smoke_detection_verified": False,
        "cigarette_identity_verified": False,
        "production_release_allowed": False,
        "rows": rows,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--threezone", type=Path, required=True)
    p.add_argument("--yunet", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    d = audit(args.threezone, args.yunet)
    if args.out.exists():
        raise SystemExit("Refusing to overwrite an existing audit")
    args.out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in d.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
