"""G2 readiness gate: no automated approval and no holdout contamination.

The gate only reports readiness based on independent source and explicit human
decisions. It does not run models, edit YouTube or unlock review material.
"""
from __future__ import annotations

from typing import Any

from .seo_editorial_decisions import create_review_manifest


def assess_g2_holdout_readiness(
    *, cohort: dict[str, Any], handoff: dict[str, Any],
    source_coverage: dict[str, bool],
    validated_decisions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = cohort.get("review")
    holdout = cohort.get("holdout_locked")
    if not isinstance(review, list) or not isinstance(holdout, list):
        raise ValueError("INVALID_LOCKED_COHORT")
    review_ids = [x.get("video_id") for x in review]
    holdout_ids = [x.get("video_id") for x in holdout]
    if (len(review_ids) != 30 or len(holdout_ids) != 10 or
            len(set(review_ids + holdout_ids)) != 40):
        raise ValueError("INVALID_COHORT_SPLIT")
    if set(source_coverage) != set(review_ids):
        raise ValueError("INCOMPLETE_SOURCE_AUDIT")
    if not isinstance(handoff.get("records"), list):
        raise ValueError("INVALID_HANDOFF")
    manifest = create_review_manifest(handoff)
    cards = handoff["records"]
    if any(c["video_id"] in holdout_ids for c in cards):
        raise ValueError("HOLDOUT_LEAK_IN_REVIEW")
    if any(c.get("publication_allowed") is not False for c in cards):
        raise ValueError("UNSAFE_REVIEW_RECORD")
    reviewed_ids = {x["video_id"] for x in cards}
    missing_videos = sorted(set(review_ids) - reviewed_ids)
    incomplete = sorted(vid for vid, ok in source_coverage.items() if not ok)
    blocked_cards = [
        (c["video_id"], c["record_id"]) for c in cards
        if c["status"] in {"BLOCKED", "VAGUE_TOPIC_NEEDS_REVIEW"}
    ]
    total_decisions = 0
    pending = len(cards)
    revisions = 0
    rejected = 0
    decisions_valid = False
    if validated_decisions is not None:
        d = validated_decisions
        if (d.get("schema") != "RG_G2_HUMAN_REVIEW_VALIDATED_V1" or
                d.get("manifest_sha256") != manifest["manifest_sha256"] or
                d.get("publication_allowed") is not False or
                d.get("g2_accepted") is not False):
            raise ValueError("INVALID_REVIEW_DECISIONS")
        decisions = d.get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("INVALID_REVIEW_DECISIONS")
        total_decisions = len(decisions)
        if total_decisions != d.get("reviewed") or (
                d.get("pending") != len(cards) - total_decisions):
            raise ValueError("INCONSISTENT_REVIEW_COUNTS")
        pending = len(cards) - total_decisions
        revisions = sum(x.get("decision") == "revise" for x in decisions)
        rejected = sum(x.get("decision") == "reject" for x in decisions)
        decisions_valid = True
    blockers = {
        "source_incomplete_videos": incomplete,
        "review_missing_videos": missing_videos,
        "blocked_or_vague_cards": len(blocked_cards),
        "pending_human_cards": pending,
        "human_revisions_pending_new_review": revisions,
        "human_rejections_pending_rework": rejected,
        "human_manifest_valid": decisions_valid,
    }
    ready = (not incomplete and not missing_videos and not blocked_cards and
             pending == 0 and revisions == 0 and rejected == 0 and
             decisions_valid)
    return {
        "schema": "RG_G2_HOLDOUT_READINESS_V1",
        "review_video_count": 30,
        "holdout_reserved_count": 10,
        "holdout_evaluated": 0,
        "source_grounded_cards": len(cards),
        "human_reviewed": total_decisions,
        "blockers": blockers,
        "holdout_ready": bool(ready),
        "g2_accepted": False,
        "publication_allowed": False,
    }
