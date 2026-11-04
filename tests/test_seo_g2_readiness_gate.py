import pytest

from rg_youtube_control.seo_editorial_decisions import (
    create_review_manifest, validate_editorial_decisions,
)
from rg_youtube_control.seo_g2_readiness_gate import assess_g2_holdout_readiness


def fixture():
    review = [{"video_id": f"Video{i:06d}"} for i in range(30)]
    holdout = [{"video_id": f"Hidden{i:05d}"} for i in range(10)]
    packet = {"records": [
        {"video_id": x["video_id"], "record_id": 1,
         "source_quote": "A source quotation from an existing caption is required.",
         "source_context": "A source quotation from an existing caption is required.",
         "initial_topic": "Тема розмови",
         "initial_summary": "Автор розповідає про тему, записану в джерелі.",
         "status": "SOURCE_QUOTED_AI_RISK", "publication_allowed": False}
        for x in review
    ]}
    return ({"review": review, "holdout_locked": holdout}, packet,
            {x["video_id"]: True for x in review})


def test_blocked_without_human_review():
    cohort, packet, coverage = fixture()
    report = assess_g2_holdout_readiness(cohort=cohort,handoff=packet,
                                          source_coverage=coverage)
    assert not report["holdout_ready"]
    assert report["blockers"]["pending_human_cards"]==30
    assert report["holdout_evaluated"]==0
    assert not report["publication_allowed"]


def test_missing_source_blocks_even_with_all_approved():
    cohort,packet,coverage=fixture()
    m=create_review_manifest(packet)
    submitted={"schema":"RG_G2_HUMAN_DECISIONS_V1","manifest_sha256":m["manifest_sha256"],
        "reviewer":"genuine-editor","decisions":[{**c,"decision":"approve"}
          for c in m["cards"]]}
    checked=validate_editorial_decisions(packet=packet,submission=submitted)
    coverage[cohort["review"][5]["video_id"]]=False
    report=assess_g2_holdout_readiness(cohort=cohort,handoff=packet,
        source_coverage=coverage,validated_decisions=checked)
    assert not report["holdout_ready"]
    assert len(report["blockers"]["source_incomplete_videos"])==1


def test_only_fully_accepted_review_makes_holdout_eligible_not_g2_accepted():
    cohort,packet,coverage=fixture()
    m=create_review_manifest(packet)
    submitted={"schema":"RG_G2_HUMAN_DECISIONS_V1","manifest_sha256":m["manifest_sha256"],
        "reviewer":"genuine-editor","decisions":[{**c,"decision":"approve"}
          for c in m["cards"]]}
    checked=validate_editorial_decisions(packet=packet,submission=submitted)
    report=assess_g2_holdout_readiness(cohort=cohort,handoff=packet,
        source_coverage=coverage,validated_decisions=checked)
    assert report["holdout_ready"]
    assert report["g2_accepted"] is False
    assert report["publication_allowed"] is False
    assert report["holdout_evaluated"] == 0


def test_a_holdout_card_leaking_into_review_fails():
    cohort,packet,coverage=fixture()
    packet["records"][0]["video_id"] = cohort["holdout_locked"][0]["video_id"]
    with pytest.raises(ValueError,match="HOLDOUT_LEAK"):
        assess_g2_holdout_readiness(cohort=cohort,handoff=packet,
                                     source_coverage=coverage)


def test_review_revision_not_approval():
    cohort,packet,coverage=fixture()
    m=create_review_manifest(packet)
    decisions=[{**c,"decision":"approve"} for c in m["cards"]]
    decisions[0]["decision"]="revise"
    decisions[0]["corrected_topic"]="Уточнена тема"
    decisions[0]["corrected_summary"]="Відредагований короткий опис справжньої репліки."
    decisions[0]["note"]="Precise attribution required."
    checked=validate_editorial_decisions(packet=packet,submission={
        "schema":"RG_G2_HUMAN_DECISIONS_V1","manifest_sha256":m["manifest_sha256"],
        "reviewer":"editor","decisions":decisions})
    report=assess_g2_holdout_readiness(cohort=cohort,handoff=packet,
        source_coverage=coverage,validated_decisions=checked)
    assert report["holdout_ready"] is False
    assert report["blockers"]["human_revisions_pending_new_review"] == 1
