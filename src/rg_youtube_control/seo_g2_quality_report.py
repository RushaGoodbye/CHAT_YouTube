"""G2 cohort acceptance report: distinguish source coverage from SEO quality.

Only signed-off human item scores can close editorial accuracy. The source gate,
model risk opinions, and test suite passing NEVER authorize publication.
"""
from __future__ import annotations

from typing import Any


def summarize_g2_progress(
    *, cohort: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    reviews = cohort.get("review") or []
    holdout = cohort.get("holdout_locked") or []
    review_ids = {v["video_id"] for v in reviews}
    holdout_ids = {v["video_id"] for v in holdout}
    evaluated_ids = [x.get("video_id") for x in results]
    if (len(review_ids) != len(reviews)
            or len(holdout_ids) != len(holdout)
            or review_ids & holdout_ids
            or len(set(evaluated_ids)) != len(evaluated_ids)):
        raise ValueError("INVALID_COHORT_PARTITION")
    if not set(evaluated_ids).issubset(review_ids):
        raise ValueError("HOLDOUT_OR_UNKNOWN_VIDEO_EXPOSED")
    ready = [x for x in results if x.get("status") == "READY_FOR_HUMAN"]
    blocked = [x for x in results if x.get("status") != "READY_FOR_HUMAN"]
    source_blocks = sum(int(x.get("blocks") or 0) for x in ready)
    source_quotes = sum(int(x.get("accepted_quotes") or 0) for x in ready)
    rejected = sum(int(x.get("rejected_quotes") or 0) for x in ready)
    missing_blocks = sum(len(x.get("missing_blocks") or []) for x in ready)
    complete = (cohort.get("acceptance_cohort_ready") is True
                and len(reviews) >= 30 and len(holdout) >= 10
                and len(ready) == len(reviews) and not blocked
                and missing_blocks == 0)
    return {
        "schema": "RG_G2_REVIEW_COHORT_PROGRESS_V1",
        "verified_sources": cohort.get("available_real_verified_sources", 0),
        "review_required": len(reviews),
        "review_processed": len(results),
        "source_grounded_review_items": len(ready),
        "source_block_count": source_blocks,
        "source_grounded_quote_count": source_quotes,
        "original_model_quotes_rejected": rejected,
        "missing_source_blocks_in_ready": missing_blocks,
        "blocked_review_videos": [
            {"video_id":v.get("video_id"), "status":v.get("status")}
            for v in blocked
        ],
        "holdout_reserved": len(holdout),
        "holdout_exposed": 0,
        "technical_source_coverage_ready": complete,
        "human_editorial_scores_verified": 0,
        "editorial_accuracy_accepted": False,
        "holdout_quality_accepted": False,
        "g2_accepted": False,
        "publication_allowed": False,
    }
