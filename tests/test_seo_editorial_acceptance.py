import json
import pytest
from rg_youtube_control.seo_editorial_acceptance import (
    build_editorial_review_packet, independent_llm_critique
)
VID = "AbCdEfGh123"

def sample():
    return {
        "video_id": VID,
        "complete_evidence_coverage": True,
        "evidence_records": [
            {"block_index":1, "start_s":10, "end_s":14,
             "topic":"Міський транспорт",
             "model_summary_not_fact":"Учасник обговорює розвиток громадського транспорту.",
             "verbatim_quote":"We are planning a new bus route.",
             "statement_kind":"attributed_speech"}
        ],
    }

def rows():
    return [{"text":"We are planning a new bus route.","start":10,"duration":4},
            {"text":"No vote has happened yet.","start":14,"duration":4}]

def test_review_packet_contains_nearby_context_and_no_approval():
    r = build_editorial_review_packet(video_id=VID, source_records=sample(),
                                     transcript_rows=rows())
    assert len(r["records"]) == 1
    assert "No vote has happened yet" in r["records"][0]["source_context"]
    assert all(v is None for v in r["records"][0]["human_scores"].values())
    assert not r["editorial_approved"]
    assert not r["publication_allowed"]

def test_mismatched_id_or_incomplete_coverage_blocks_review():
    with pytest.raises(ValueError,match="VIDEO_ID_MISMATCH"):
        build_editorial_review_packet(video_id="QwErTyUi456",
            source_records=sample(), transcript_rows=rows())
    incomplete = sample()
    incomplete["complete_evidence_coverage"] = False
    with pytest.raises(ValueError,match="EVIDENCE_COVERAGE_INCOMPLETE"):
        build_editorial_review_packet(video_id=VID,
            source_records=incomplete, transcript_rows=rows())

def test_independent_critic_flags_risk_without_approving():
    packet=build_editorial_review_packet(video_id=VID,
        source_records=sample(),transcript_rows=rows())
    def critic(messages,**kwargs):
        assert "No vote has happened yet" in messages[-1]["content"]
        return json.dumps({"risk":"high","issues":["Unsupported vote claim"],
                           "reason":"Unconfirmed in source"})
    result=independent_llm_critique(packet=packet,chat=critic,model="independent")
    assert result["checked"] == 1
    assert result["findings"][0]["risk"] == "high"
    assert not result["editorial_approved"]
    assert not result["publication_allowed"]

def test_critic_failure_is_high_risk():
    packet=build_editorial_review_packet(video_id=VID,
        source_records=sample(),transcript_rows=rows())
    result=independent_llm_critique(packet=packet,chat=lambda *a,**k:"{}",
                                    model="independent")
    assert result["findings"][0]["risk"] == "high"

def test_critic_cannot_return_auto_approval():
    packet=build_editorial_review_packet(video_id=VID,
        source_records=sample(),transcript_rows=rows())
    result=independent_llm_critique(packet=packet,
        chat=lambda *a,**k:'{"risk":"low","issues":[],"editorial_approved":true,"publication_allowed":true}',
        model="independent")
    assert result["findings"][0]["risk"] == "low"
    assert result["editorial_approved"] is False
    assert result["publication_allowed"] is False


def test_same_generator_and_critic_cannot_be_called_independent():
    packet=build_editorial_review_packet(video_id=VID,
        source_records=sample(),transcript_rows=rows())
    with pytest.raises(ValueError,match="CRITIC_MUST_DIFFER_FROM_GENERATOR"):
        independent_llm_critique(packet=packet,chat=lambda *a,**k:'{}',
            model="rg-gemma4-12b",generator_model="RG-GEMMA4-12B")
