"""G2 validation-cohort builder. Refuse a pretend acceptance set.

Only exact-byte, independently timestamped YouTube caption acquisitions are
eligible. Draft SEO descriptions, synthetic subtitles and guessed paths are not.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
from typing import Any

from .seo_caption_manifest import audit_caption_file

MIN_REVIEW_VIDEOS = 30
MIN_HOLDOUT_VIDEOS = 10


def build_g2_cohort(
    *, caption_dir: Path, review_size: int = 30,
    holdout_size: int = 10,
) -> dict[str, Any]:
    if review_size < MIN_REVIEW_VIDEOS or holdout_size < MIN_HOLDOUT_VIDEOS:
        raise ValueError("G2_ACCEPTANCE_COHORT_TOO_SMALL")
    caption_dir = Path(caption_dir)
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for file in sorted(caption_dir.glob("*.srt")):
        video_id = file.stem
        if len(video_id) != 11:
            excluded.append({"file": file.name, "reason": "INVALID_ID"})
            continue
        try:
            manifest = json.loads(file.with_suffix(".source.json").read_text(encoding="utf-8"))
            duration_s = float(manifest["duration_s"])
            audit = audit_caption_file(video_id=video_id, path=file, duration_s=duration_s)
            if audit.get("status") == "BLOCKED_SOURCE":
                raise ValueError("CAPTION_AUDIT_BLOCKED")
            raw_hash = sha256(file.read_bytes()).hexdigest()
            eligible.append({
                "video_id": video_id, "duration_s": duration_s,
                "srt_sha256": raw_hash, "caption_file": str(file),
                "source_audit_status": audit.get("status", "PASS"),
            })
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            excluded.append({"file": file.name, "reason": str(exc)[:150]})
    # Deterministic, length-stratified selection. Stable IDs and exact hashes
    # prevent accidentally moving a previously observed source into holdout.
    ordered = sorted(eligible, key=lambda x: (x["duration_s"], x["video_id"]))
    needed = review_size + holdout_size
    ready = len(ordered) >= needed
    review, holdout = [], []
    if ready:
        selected = ordered[:needed]
        # Alternate among duration bands so review and unseen holdout both
        # contain short and long recordings rather than a length bias.
        review = [x for i, x in enumerate(selected) if i % needed < review_size]
        holdout = [x for i, x in enumerate(selected) if i % needed >= review_size]
        # keep deterministic but length-distributed holdout at spaced ranks
        positions = {round(i * (needed-1) / (holdout_size-1)) for i in range(holdout_size)}
        holdout = [x for i, x in enumerate(selected) if i in positions]
        review = [x for i, x in enumerate(selected) if i not in positions]
        if len(holdout) != holdout_size or len(review) != review_size:
            raise ValueError("COHORT_SPLIT_MISMATCH")
    return {
        "schema": "RG_G2_SOURCE_COHORT_V1",
        "available_real_verified_sources": len(eligible),
        "required_review_sources": review_size,
        "required_holdout_sources": holdout_size,
        "missing_for_acceptance": max(0, needed - len(eligible)),
        "acceptance_cohort_ready": ready,
        "review": review,
        "holdout_locked": holdout,
        "eligible_inventory": eligible,
        "excluded": excluded,
        "editorial_approved": False,
        "publication_allowed": False,
    }
