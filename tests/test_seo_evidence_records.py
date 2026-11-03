import pytest
from rg_youtube_control.seo_evidence_records import build_evidence_records

VID = "AbCdEfGh123"


def row(text, start=0.0):
    return {"text": text, "start": start, "duration": 4.0}


def report(quote, verified=True, **extra):
    block = {
        "index": 1, "start": 0.0, "end": 4.0, "verified": verified,
        "topics": [{"topic": "Тема розмови", "summary_uk": "Учасник висловлює позицію.",
                    "evidence": quote}],
    }
    block.update(extra)
    return {"blocks_analyzed": 1, "blocks_with_evidence": int(verified),
            "blocks": [block]}


def test_grounded_speech_preserves_quote_and_timestamp():
    q = "Our town is discussing bus and rail transport."
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q), transcript_rows=[row(q, 64.0)])
    assert len(result["evidence_records"]) == 1
    item = result["evidence_records"][0]
    assert item["start_s"] == 64.0
    assert item["verbatim_quote"] == q
    assert item["statement_kind"] == "attributed_speech"
    assert not item["factual_truth_verified"]
    assert result["publication_allowed"] is False


def test_question_not_treated_as_external_fact():
    q = "Why are tickets so expensive now?"
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q), transcript_rows=[row(q)])
    assert result["evidence_records"][0]["statement_kind"] == "question"
    assert result["needs_review"]


def test_hallucinated_quote_is_rejected():
    result = build_evidence_records(video_id=VID,
        timeline_report=report("The minister resigned last night"),
        transcript_rows=[row("We discussed the climate and weather today")])
    assert result["evidence_records"] == []
    assert result["rejected_evidence"][0]["reason"] == "QUOTE_NOT_IN_SOURCE"


def test_two_different_topics_remain_distinct():
    quote1 = "This city needs a new tram service."
    quote2 = "Our schools need additional teachers."
    first = report(quote1)["blocks"][0]
    second = report(quote2, index=2, start=15.0, end=19.0)["blocks"][0]
    merged = {"blocks_analyzed": 2, "blocks_with_evidence": 2,
              "blocks": [first, second]}
    result = build_evidence_records(video_id=VID,timeline_report=merged,
        transcript_rows=[row(quote1),row(quote2,15.0)])
    assert len(result["evidence_records"]) == 2
    assert [r["start_s"] for r in result["evidence_records"]] == [0.0,15.0]


def test_unverified_blocks_not_presented_as_evidence():
    q = "We might go to the beach today."
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q, verified=False),transcript_rows=[row(q)])
    assert result["evidence_records"] == []


def test_no_fake_provenance_from_invalid_video_id():
    with pytest.raises(ValueError,match="INVALID_VIDEO_ID"):
        build_evidence_records(video_id="not-a-youtube-id",
            timeline_report=report("A test quotation with sufficient length."),
            transcript_rows=[row("A test quotation with sufficient length.")])


def test_quote_spanning_rows_requires_block_text():
    q = "The city council voted today about new"
    r1 = row("The city council voted today",0)
    r2 = row("about new bus lanes",4)
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q, end=8.0),transcript_rows=[r1,r2])
    assert len(result["evidence_records"]) == 1
    assert result["evidence_records"][0]["timestamp_precision"] == "timeline_block"
    assert result["evidence_records"][0]["factual_truth_verified"] is False
