#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R27 video-frame appearance tracking: candidate mask geometry ONLY.

Requires independent semantic anchors on the exact 886_6 montage, not the
multi-hour 886.mp4 stream. A tracked patch does NOT establish that the object
is still a cigarette or bottle; abstention is expected and all output stays
QA_NOT_RELEASE. Original MP4, audio, Premiere XML, and Studio stay untouched.

Dependencies for this SHADOW-only path: opencv-python-headless and numpy.
"""
from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path

SCHEMA = "RG_R27_TRACK_ANCHORS_V1"
OUTPUT_SCHEMA = "RG_R27_TRACK_PROPOSALS_V1"
CATEGORIES = {"bottle", "cigarette", "smoking_hand", "smoking_mouth", "smoke"}
PARTICIPANTS = {"host", "guest"}


def _bbox(box, width, height, label):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError(label + ": expected bbox [x0,y0,x1,y1]")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) for v in box):
        raise ValueError(label + ": invalid bbox numbers")
    x0, y0, x1, y1 = [float(v) for v in box]
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(label + ": bbox outside image")
    return (x0, y0, x1, y1)


def _overlap_ratio(a, b):
    x0, y0, x1, y1 = a
    xx0, yy0, xx1, yy1 = b
    area = max(0, min(x1, xx1) - max(x0, xx0)) * max(
        0, min(y1, yy1) - max(y0, yy0))
    return area / max(1., (x1-x0)*(y1-y0))


def _inside(box, roi):
    return box[0] >= roi[0] and box[1] >= roi[1] and box[2] <= roi[2] and box[3] <= roi[3]


def _rect_patch(frame, box):
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    return frame[y0:y1, x0:x1]


def _image_gray(frame):
    import cv2
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _scene_diff(prev, cur, roi):
    import cv2
    import numpy as np
    before = _rect_patch(prev, roi)
    after = _rect_patch(cur, roi)
    if before.size == 0 or after.size == 0:
        return math.inf
    before = cv2.resize(_image_gray(before), (80, 55))
    after = cv2.resize(_image_gray(after), (80, 55))
    return float(np.mean(cv2.absdiff(before, after)))


def _match_near(frame, template, previous_box, roi, radius, min_score):
    import cv2
    prev_w, prev_h = template.shape[1], template.shape[0]
    x0, y0, x1, y1 = previous_box
    left = max(int(roi[0]), int(round(x0 - radius)))
    top = max(int(roi[1]), int(round(y0 - radius)))
    right = min(int(roi[2]), int(round(x1 + radius)))
    bottom = min(int(roi[3]), int(round(y1 + radius)))
    search = _image_gray(frame[top:bottom, left:right])
    if search.shape[0] < prev_h or search.shape[1] < prev_w:
        return None
    _, peak, _, pos = cv2.minMaxLoc(
        cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
    if not math.isfinite(peak) or peak < min_score:
        return None
    box = (left + pos[0], top + pos[1],
           left + pos[0] + prev_w, top + pos[1] + prev_h)
    shift = math.dist(((x0+x1)/2., (y0+y1)/2.),
                      ((box[0]+box[2])/2., (box[1]+box[3])/2.))
    if shift > radius * 0.82 or not _inside(box, roi):
        return None
    return (box, float(peak))


def _mask(box, roi, margin=0.2):
    x0, y0, x1, y1 = box
    dx = max(7., (x1-x0)*margin)
    dy = max(7., (y1-y0)*margin)
    return [round(v, 3) for v in (
        max(roi[0], x0-dx), max(roi[1], y0-dy),
        min(roi[2], x1+dx), min(roi[3], y1+dy))]


def validate(config):
    if not isinstance(config, dict) or config.get("schema") != SCHEMA:
        raise ValueError("Unexpected anchor manifest schema")
    count = config.get("frame_count")
    w, h = config.get("width"), config.get("height")
    if any(isinstance(v, bool) or not isinstance(v, int) or
           not 1 <= v <= limit for v, limit in ((count, 1000000),
                                                 (w, 16000), (h, 16000))):
        raise ValueError("Invalid video dimensions or frame count")
    rois = config.get("participant_rois", {})
    if not isinstance(rois, dict) or set(rois) != PARTICIPANTS:
        raise ValueError("Explicit host and guest ROIs required")
    parsed_rois = {side: _bbox(box, w, h, side+" ROI")
                   for side, box in rois.items()}
    cuts = config.get("cut_frames")
    if (not isinstance(cuts, list) or
        any(isinstance(v, bool) or not isinstance(v, int) or not 0 < v < count for v in cuts) or
        len(set(cuts)) != len(cuts)):
        raise ValueError("Explicit cut_frames list required (may be empty)")
    cuts = sorted(cuts)
    max_span = config.get("max_track_frames", 18)
    if isinstance(max_span, bool) or not isinstance(max_span, int) or not 1 <= max_span <= 60:
        raise ValueError("max_track_frames must be 1..60")
    anchors = config.get("anchors")
    if not isinstance(anchors, list):
        raise ValueError("Missing anchors array")
    for i, a in enumerate(anchors):
        if not isinstance(a, dict) or a.get("participant") not in PARTICIPANTS or a.get("object") not in CATEGORIES:
            raise ValueError("Invalid anchor class or side")
        f = a.get("frame")
        if isinstance(f, bool) or not isinstance(f, int) or not 0 <= f < count:
            raise ValueError("Anchor frame out of range")
        if a.get("semantic_verified") is not True or a.get("provenance") != "independent_visual_review":
            raise ValueError("Unverified detector-only anchor cannot authorize a track")
        box = _bbox(a.get("bbox"), w, h, "anchor")
        if not _inside(box, parsed_rois[a["participant"]]):
            raise ValueError("Anchor outside participant ROI")
        if min(box[2]-box[0], box[3]-box[1]) < 8:
            raise ValueError("Anchor too small for appearance tracking")
        if not isinstance(a.get("track_id"), str) or not a["track_id"] or len(a["track_id"]) > 80:
            raise ValueError("track_id is required to distinguish simultaneous objects")
    absent = set()
    for a in config.get("verified_absent", []):
        f = a.get("frame")
        side, obj = a.get("participant"), a.get("object")
        if (isinstance(f, bool) or not isinstance(f, int) or not 0 <= f < count or
            side not in PARTICIPANTS or obj not in CATEGORIES or
            a.get("semantic_verified") is not True or
            a.get("provenance") != "independent_visual_review"):
            raise ValueError("Invalid unverified negative observation")
        absent.add((f, side, obj))
    for a in anchors:
        if (a["frame"], a["participant"], a["object"]) in absent:
            raise ValueError("Contradictory present and absent observations")
    return (count, w, h, parsed_rois, cuts, max_span, absent)


def _scene_limits(frame, cuts, count):
    low = max([0] + [c for c in cuts if c <= frame])
    high = min([count] + [c for c in cuts if c > frame])
    return low, high


def track(get_frame, manifest):
    """Video-derived *candidates*. get_frame(index) -> BGR uint8 ndarray.

    The tracker deliberately does NOT interpolate past cuts, verified
    absence or an appearance failure; no prediction-only blur frames.
    """
    import numpy as np
    count, width, height, rois, cuts, span, absent = validate(manifest)
    min_score = float(manifest.get("min_match_score", 0.88))
    scene_threshold = float(manifest.get("scene_change_threshold", 33.0))
    if (not math.isfinite(min_score) or not 0.70 <= min_score <= 0.999 or
        not math.isfinite(scene_threshold) or not 12 <= scene_threshold <= 70):
        raise ValueError("Invalid match / scene thresholds")
    candidates = []
    abstentions = []
    # A hard memory cap is mandatory for long 1920x1080 dialogues.
    @lru_cache(maxsize=8)
    def frame_at(i):
        frame = get_frame(i)
        if not isinstance(frame, np.ndarray) or frame.shape != (height, width, 3) or frame.dtype != np.uint8:
            raise ValueError("Video frame missing or unexpected BGR format at " + str(i))
        return frame

    for anchor_idx, a in enumerate(manifest["anchors"]):
        f0, side, obj, ident = (a["frame"], a["participant"], a["object"], a["track_id"])
        box = _bbox(a["bbox"], width, height, "seed")
        roi = rois[side]
        origin = frame_at(f0)
        templ = _image_gray(_rect_patch(origin, box))
        if templ.size < 64 or min(templ.shape) < 8 or float(np.std(templ)) < 9:
            abstentions.append({"anchor": anchor_idx, "frame": f0, "reason": "SEED_TOO_TEXTURELESS"})
            continue
        x0, y0, x1, y1 = box
        radius = min(100., max(14., 0.5 * math.hypot(x1-x0, y1-y0)))
        clip_start, clip_end = _scene_limits(f0, cuts, count)
        out = {f0: (box, 1.0)}
        for direction in (-1, 1):
            last_box, last_frame = box, origin
            for step in range(1, span + 1):
                i = f0 + step * direction
                if i < clip_start or i >= clip_end:
                    abstentions.append({"anchor": anchor_idx, "frame": i,
                                        "reason": "SCENE_CUT_OR_CLIP_BOUNDARY"})
                    break
                if (i, side, obj) in absent:
                    abstentions.append({"anchor": anchor_idx, "frame": i,
                                        "reason": "SEMANTICALLY_VERIFIED_ABSENT"})
                    break
                curr = frame_at(i)
                if _scene_diff(last_frame, curr, roi) >= scene_threshold:
                    abstentions.append({"anchor": anchor_idx, "frame": i,
                                        "reason": "VISUAL_SCENE_CHANGE"})
                    break
                proposal = _match_near(curr, templ, last_box, roi, radius, min_score)
                if proposal is None:
                    abstentions.append({"anchor": anchor_idx, "frame": i,
                                        "reason": "APPEARANCE_OR_MOTION_AMBIGUOUS"})
                    break
                next_box, score = proposal
                if not _inside(next_box, roi):
                    raise AssertionError("Escaped participant ROI")
                out[i] = next_box, score
                last_frame, last_box = curr, next_box
        for i, (position, score) in out.items():
            candidates.append({
                "frame": i, "start": i, "end": i + 1,
                "participant": side, "object": obj, "track_id": ident,
                "bbox": _mask(position, roi),
                "source_object_bbox": [round(x, 3) for x in position],
                "appearance_score": round(score, 5),
                "anchor_frame": f0,
                "semantic_verified_for_this_frame": i == f0,
                "status": "CANDIDATE_ONLY",
            })
    # One track_id can have two independently verified anchors. Keep strongest
    # proposal for a given frame; never merge across two separate object IDs.
    unique = {}
    for c in candidates:
        key = (c["frame"], c["participant"], c["object"], c["track_id"])
        if key not in unique or c["appearance_score"] > unique[key]["appearance_score"]:
            unique[key] = c
    result = sorted(unique.values(), key=lambda c: (c["frame"], c["participant"],
                                                    c["object"], c["track_id"]))
    collisions = []
    by_semantic = {}
    for c in result:
        k = (c["frame"], c["participant"], c["object"])
        by_semantic.setdefault(k, set()).add(c["track_id"])
    for k, ids in by_semantic.items():
        if len(ids) > 1:
            collisions.append({"frame": k[0], "participant": k[1], "object": k[2],
                               "track_ids": sorted(ids), "reason": "MULTIPLE_OBJECTS_REQUIRE_VISUAL_REVIEW"})
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "SHADOW_CANDIDATES_UNVERIFIED",
        "frame_count": count, "width": width, "height": height,
        "source_video_sha256_verified": False,
        "anchors": len(manifest["anchors"]), "candidate_mask_frames": len(result),
        "candidates": result, "abstentions": abstentions,
        "collisions": collisions, "semantic_reverification_required": True,
        "no_object_found_does_not_mean_absent": True,
        "pixel_blur_qa_verified": False, "audio_unchanged_verified": False,
        "release_ready": False, "studio_modified": False,
    }


class VideoSource:
    def __init__(self, path, expected):
        import cv2
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError("Cannot open input video")
        self.cv2 = cv2
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (self.count, self.width, self.height) != expected:
            self.cap.release()
            raise ValueError("Input is not the annotated dialogue: expected "
                             + str(expected) + " got " + str((self.count, self.width, self.height)))
        self.last = -2

    def get(self, i):
        if i != self.last + 1:
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, i)
        success, image = self.cap.read()
        self.last = i
        if not success:
            raise ValueError("Frame decode failed at " + str(i))
        return image

    def close(self):
        self.cap.release()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--anchors", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    source = a.video.resolve()
    ann = a.anchors.resolve()
    dst = a.output.resolve()
    if not source.is_file() or not ann.is_file() or dst in (source, ann) or dst.suffix.lower() != ".json":
        raise SystemExit("Refusing absent input or overwrite of source")
    manifest = json.loads(ann.read_text(encoding="utf-8-sig"))
    count, width, height, _, _, _, _ = validate(manifest)
    video = VideoSource(source, (count, width, height))
    try:
        report = track(video.get, manifest)
    finally:
        video.close()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("anchors", "candidate_mask_frames", "status", "release_ready")}))
    # Candidate generation succeeded; non-release status is NOT a pipeline crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
