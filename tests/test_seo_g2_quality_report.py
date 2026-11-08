import pytest
from rg_youtube_control.seo_g2_quality_report import summarize_g2_progress

def cohort():
    return {"acceptance_cohort_ready":True,"available_real_verified_sources":40,
            "review":[{"video_id":f"V{i:010d}"} for i in range(30)],
            "holdout_locked":[{"video_id":f"H{i:010d}"} for i in range(10)]}

def ready(i):
    return {"video_id":f"V{i:010d}","status":"READY_FOR_HUMAN",
            "blocks":3,"accepted_quotes":4,"rejected_quotes":1,
            "missing_blocks":[]}

def test_fully_grounded_thirty_never_pass_editorial_without_labels():
    result=summarize_g2_progress(cohort=cohort(),results=[ready(i) for i in range(30)])
    assert result["technical_source_coverage_ready"]
    assert result["source_block_count"]==90
    assert result["source_grounded_quote_count"]==120
    assert result["original_model_quotes_rejected"]==30
    assert result["human_editorial_scores_verified"]==0
    assert result["g2_accepted"] is False
    assert result["publication_allowed"] is False

def test_missing_review_source_stays_pending():
    result=summarize_g2_progress(cohort=cohort(),results=[ready(i) for i in range(29)])
    assert not result["technical_source_coverage_ready"]
    assert result["review_processed"]==29

def test_holdout_accidentally_exposed_raises():
    items=[ready(i) for i in range(30)]
    items[3]["video_id"]="H0000000000"
    with pytest.raises(ValueError,match="HOLDOUT_OR_UNKNOWN_VIDEO_EXPOSED"):
        summarize_g2_progress(cohort=cohort(),results=items)

def test_blocked_model_work_does_not_count_as_coverage():
    items=[ready(i) for i in range(30)]
    items[10]["status"]="BLOCKED_MODEL_OR_SOURCE"
    result=summarize_g2_progress(cohort=cohort(),results=items)
    assert not result["technical_source_coverage_ready"]
    assert result["blocked_review_videos"][0]["video_id"]=="V0000000010"
