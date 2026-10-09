"""Four-layer smoking masks and a fail-closed, source-bound review gate.

Importing this module does not load models, modify Studio, or write media.
Model proposals are never promoted to independently reviewed ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

VERSION = "RG_SMOKING_COMPLIANCE_BLUR_1.0.0_RC1"
SCHEMA = "RG_SMOKING_COMPLIANCE_SCAN_V1"
LAYERS = ("cigarette", "grip", "smoke", "mouth")
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ReviewRequired(RuntimeError):
    """A result is incomplete, ambiguous, unsafe, or lacks independent review."""


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def valid_sha(value):
    return isinstance(value, str) and SHA_PATTERN.fullmatch(value) is not None


def validate_ranges(ranges):
    if not isinstance(ranges, list) or not ranges:
        raise ReviewRequired("SOURCE_RANGES_MISSING")
    previous_end = -1
    normalized = []
    for pair in ranges:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ReviewRequired("SOURCE_RANGE_INVALID")
        a, b = pair
        if type(a) is not int or type(b) is not int or not 0 <= a < b:
            raise ReviewRequired("SOURCE_RANGE_INVALID")
        if a < previous_end:
            raise ReviewRequired("SOURCE_RANGES_OVERLAP_OR_UNSORTED")
        normalized.append([a, b])
        previous_end = b
    return normalized


def cache_key(source_sha256, ranges, model_hashes, options, dialogue):
    if not valid_sha(source_sha256) or not model_hashes:
        raise ReviewRequired("CACHE_IDENTITY_INCOMPLETE")
    if not all(valid_sha(v) for v in model_hashes.values()):
        raise ReviewRequired("MODEL_IDENTITY_INVALID")
    return canonical_hash({"version": VERSION, "source_sha256": source_sha256,
        "ranges": validate_ranges(ranges), "models": model_hashes,
        "options": options, "dialogue": dialogue})


@dataclass(frozen=True)
class MaskPolicy:
    # Bounds control local proposals. They are not calibrated detector accuracy.
    max_area_fraction: float = 0.12
    padding_px: int = 10
    feather_px: int = 5
    blur_sigma: float = 25.0

    def __post_init__(self):
        if not math.isfinite(self.max_area_fraction) or not 0 < self.max_area_fraction <= .15:
            raise ValueError("Local-mask area bound invalid")
        if type(self.padding_px) is not int or not 0 <= self.padding_px <= 30:
            raise ValueError("Mask padding invalid")
        if type(self.feather_px) is not int or not 0 <= self.feather_px <= 15:
            raise ValueError("Mask feather invalid")
        if not math.isfinite(self.blur_sigma) or not 15 <= self.blur_sigma <= 80:
            raise ValueError("Blur strength outside supported range")


def compose_masks(layers, required, shape, roi, forbidden=None, policy=None):
    """Validate every layer before combining. Never silently crop a bad mask."""
    import cv2
    import numpy as np
    policy = policy or MaskPolicy()
    if set(layers) != set(LAYERS) or set(required) != set(LAYERS):
        raise ReviewRequired("FOUR_LAYER_RECORD_REQUIRED")
    if not all(type(v) is bool for v in required.values()):
        raise ReviewRequired("REQUIRED_LAYER_OBSERVATION_UNKNOWN")
    if len(shape) != 2 or any(type(v) is not int or v <= 0 for v in shape):
        raise ReviewRequired("FRAME_SHAPE_INVALID")
    h, w = shape
    if not isinstance(roi, (tuple, list)) or len(roi) != 4:
        raise ReviewRequired("LOCAL_ROI_INVALID")
    x0, y0, x1, y1 = roi
    if any(type(v) is not int for v in roi) or not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ReviewRequired("LOCAL_ROI_INVALID")
    permitted = np.zeros(shape, bool)
    permitted[y0:y1, x0:x1] = True
    union = np.zeros(shape, bool)
    metrics = {}
    for name in LAYERS:
        arr = np.asarray(layers[name])
        if arr.shape != shape or arr.dtype not in (np.dtype(bool), np.dtype("uint8")):
            raise ReviewRequired("MASK_SHAPE_OR_DTYPE_INVALID:" + name)
        if arr.dtype != bool and not np.isin(arr, (0, 1, 255)).all():
            raise ReviewRequired("MASK_NOT_BINARY:" + name)
        mask = arr > 0
        pixels = int(mask.sum())
        if required[name] and pixels == 0:
            raise ReviewRequired("REQUIRED_MASK_MISSING:" + name)
        if not required[name] and pixels:
            raise ReviewRequired("UNREQUESTED_MASK:" + name)
        if (mask & ~permitted).any():
            raise ReviewRequired("MASK_OUTSIDE_LOCAL_ROI:" + name)
        if forbidden is not None:
            deny = np.asarray(forbidden)
            if deny.shape != shape or deny.dtype != bool:
                raise ReviewRequired("FORBIDDEN_REGION_INVALID")
            if (mask & deny).any():
                raise ReviewRequired("VERIFIED_UNRELATED_OBJECT_OVERLAP:" + name)
        metrics[name] = {"required": required[name], "pixels": pixels}
        union |= mask
    if not any(required.values()):
        raise ReviewRequired("NO_CONFIRMED_SMOKING_TARGET")
    core = union.astype(np.uint8)
    padding = policy.padding_px
    expanded = cv2.dilate(core, np.ones((padding * 2 + 1,) * 2, np.uint8)) if padding else core
    # Padding reaching a boundary is a warning requiring a larger verified ROI.
    if (expanded.astype(bool) & ~permitted).any():
        raise ReviewRequired("PADDED_MASK_OUTSIDE_LOCAL_ROI")
    if forbidden is not None and (expanded.astype(bool) & forbidden).any():
        raise ReviewRequired("PADDED_MASK_OVERLAPS_UNRELATED_OBJECT")
    sigma = policy.feather_px
    alpha = expanded.astype(np.float32)
    if sigma:
        alpha = cv2.GaussianBlur(alpha, (sigma * 6 + 1,) * 2, sigma)
    # Every proposed target pixel gets the full blur, including thin cigarettes.
    alpha[union] = 1.0
    alpha[alpha < .002] = 0.0
    support = alpha > 0
    if (support & ~permitted).any():
        raise ReviewRequired("FEATHER_OUTSIDE_LOCAL_ROI")
    if forbidden is not None and (support & forbidden).any():
        raise ReviewRequired("FEATHER_OVERLAPS_UNRELATED_OBJECT")
    area = int(support.sum()) / (w * h)
    if area > policy.max_area_fraction:
        raise ReviewRequired("MASK_AREA_TOO_LARGE")
    return alpha, {"layers": metrics, "mask_area_fraction": area,
        "core_pixels": int(union.sum()), "support_pixels": int(support.sum())}


def blur_frame(frame, alpha, policy=None):
    import cv2
    import numpy as np
    policy = policy or MaskPolicy()
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ReviewRequired("FRAME_FORMAT_INVALID")
    if alpha.shape != frame.shape[:2] or not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
        raise ReviewRequired("ALPHA_INVALID")
    smooth = cv2.GaussianBlur(frame, (0, 0), policy.blur_sigma)
    mixed = np.rint(frame.astype(np.float32) * (1 - alpha[..., None]) +
                    smooth.astype(np.float32) * alpha[..., None]).astype(np.uint8)
    mixed[alpha == 0] = frame[alpha == 0]
    return mixed


def evaluate_scan(scan, *, source_sha256, ranges, dialogue, independent_review=None):
    """Release depends on source/timeline-bound external review, never a score."""
    failures = []
    try:
        wanted = validate_ranges(ranges)
    except ReviewRequired as e:
        return {"passed": False, "release_allowed": False, "status": "REVIEW_REQUIRED", "failures": [str(e)]}
    if dialogue == "886_5":
        failures.append("886_5_QUARANTINED_NO_EXPORT")
    if not isinstance(scan, dict):
        scan = {}
    if scan.get("schema") != SCHEMA or scan.get("version") != VERSION:
        failures.append("SCAN_SCHEMA_OR_VERSION_INVALID")
    if not valid_sha(source_sha256) or scan.get("source_sha256") != source_sha256:
        failures.append("SOURCE_IDENTITY_MISMATCH")
    if scan.get("source_ranges_frames") != wanted or scan.get("dialogue") != dialogue:
        failures.append("SCAN_SCOPE_MISMATCH")
    if scan.get("inference_completed") is not True:
        failures.append("SCAN_NOT_COMPLETED")
    # Ordered interval coverage is linear in frame count, and detects duplicates,
    # omissions, reordered frames and attempts to include unrelated references.
    rows = scan.get("frames")
    if not isinstance(rows, list):
        rows = []
    expected = (n for a, b in wanted for n in range(a, b))
    for row in rows:
        target = next(expected, None)
        if not isinstance(row, dict) or type(row.get("source_frame")) is not int or row.get("source_frame") != target:
            failures.append("TIMELINE_FRAME_COVERAGE_INVALID")
            break
        if row.get("state") not in ("CONFIRMED_SMOKING", "VERIFIED_NEGATIVE"):
            failures.append("AMBIGUOUS_OR_LOST_TRACK")
        if row.get("state") == "CONFIRMED_SMOKING":
            req = row.get("required")
            metrics = row.get("layer_pixels")
            if not isinstance(req, dict) or set(req) != set(LAYERS) or not all(type(v) is bool for v in req.values()) or not any(req.values()):
                failures.append("REQUIRED_LAYER_OBSERVATION_UNKNOWN")
            elif not isinstance(metrics, dict) or set(metrics) != set(LAYERS) or any(
                    type(metrics[k]) is not int or metrics[k] < 0 or req[k] != (metrics[k] > 0) for k in LAYERS):
                failures.append("REQUIRED_LAYER_MISSING_OR_UNEXPECTED")
            if row.get("local_mask_guard_passed") is not True:
                failures.append("LOCAL_MASK_GUARD_FAILED")
            if not valid_sha(row.get("mask_sha256")):
                failures.append("MASK_IDENTITY_MISSING")
        else:
            if row.get("mask_pixels") != 0:
                failures.append("NEGATIVE_FRAME_HAS_BLUR")
            # A zero-detection frame does not certify a negative. Bind its review
            # to exact pixels, with full video review checked separately below.
            if not valid_sha(row.get("decoded_frame_sha256")):
                failures.append("NEGATIVE_REFERENCE_IDENTITY_MISSING")
    if next(expected, None) is not None or len(rows) != sum(b - a for a, b in wanted):
        failures.append("TIMELINE_FRAME_COVERAGE_INVALID")
    if scan.get("failures"):
        failures.append("SCAN_HAS_UNRESOLVED_FAILURES")
    review = independent_review if isinstance(independent_review, dict) else {}
    if not review:
        failures.append("INDEPENDENT_VISUAL_REVIEW_MISSING")
    else:
        if review.get("schema") != "RG_SMOKING_INDEPENDENT_REVIEW_V1":
            failures.append("REVIEW_SCHEMA_INVALID")
        if review.get("source_sha256") != source_sha256 or review.get("source_ranges_frames") != wanted or review.get("scan_sha256") != canonical_hash(scan):
            failures.append("REVIEW_SOURCE_OR_MASKS_MISMATCH")
        for flag in ("full_timeline_reviewed", "all_required_layers_covered",
                     "no_visible_smoking_after_blur", "no_unrelated_object_blur",
                     "no_flicker", "independent_of_model_predictions"):
            if review.get(flag) is not True:
                failures.append("REVIEW_NOT_PASSED:" + flag)
        if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            failures.append("REVIEWER_MISSING")
    failures = list(dict.fromkeys(failures))
    return {"version": VERSION, "passed": not failures, "release_allowed": not failures,
        "status": "READY_AFTER_REVIEW" if not failures else "REVIEW_REQUIRED", "failures": failures}
