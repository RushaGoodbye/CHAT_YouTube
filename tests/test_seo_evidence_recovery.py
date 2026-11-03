import json
from copy import deepcopy
from rg_youtube_control.seo_evidence_recovery import recover_missing_source_blocks

VID = "AbCdEfGh123"
Q1 = "People in this city are discussing the different prices of public transport today."
Q2 = "The school committee is reviewing several plans to improve local education."

def fixture():
    rows = [{"text": Q1, "start": 0.0, "duration": 4.0},
            {"text": Q2, "start": 30.0, "duration": 4.0}]
    report = {"blocks_analyzed": 2, "blocks_with_evidence": 2, "blocks": [
        {"index": 1, "start": 0.0, "end": 4.0, "verified": True,
         "topics": [{"topic": "Транспорт громади",
                     "summary_uk": "Розмова про ціни на транспорт.",
                     "evidence": Q1}]},
        {"index": 2, "start": 30.0, "end": 34.0, "verified": True,
         "topics": [{"topic": "Школи міста",
                     "summary_uk": "Приписано неіснуючу цитату.",
                     "evidence": "The minister has reportedly resigned."}]},
    ]}
    return rows, report

def chat(messages, **kwargs):
    assert Q2 in messages[-1]["content"]
    return json.dumps({"topic": "Освіта у громаді",
                       "summary_uk": "Учасник говорить про плани для місцевої освіти."})

def test_only_missing_block_retried_once():
    rows, report = fixture()
    result = recover_missing_source_blocks(video_id=VID, timeline_report=report,
                                            transcript_rows=rows, chat=chat, model="local")
    assert result["complete_evidence_coverage"]
    assert result["recovery"]["recovered_blocks"] == [2]
    assert result["recovery"]["model_calls"] == 1
    assert result["recovery"]["recovery_requires_editorial_review"]
    assert len(result["evidence_records"]) == 2
    assert result["publication_allowed"] is False
    assert report["blocks"][1]["topics"][-1]["evidence"] == Q2

def test_lies_from_model_are_never_accepted_as_quote():
    rows, report = fixture()
    def hallucinating(messages, **kw):
        return json.dumps({"topic": "Заява про відставку",
                           "summary_uk": "Міністр пішов у відставку, за твердженням моделі.",
                           "evidence": "Prime minister resigned today."})
    result = recover_missing_source_blocks(video_id=VID, timeline_report=report,
                                            transcript_rows=rows, chat=hallucinating, model="local")
    assert report["blocks"][1]["topics"][-1]["evidence"] == Q2
    assert result["publication_allowed"] is False

def test_empty_model_response_keeps_source_blocked():
    rows, report = fixture()
    outcome = recover_missing_source_blocks(video_id=VID, timeline_report=report,
        transcript_rows=rows, chat=lambda *a,**k:'{"topic":"","summary_uk":""}', model="local")
    assert not outcome["complete_evidence_coverage"]
    assert outcome["blocks_without_grounded_quotes"] == [2]
    assert outcome["recovery"]["unrecovered"][0]["reason"] == "MODEL_RECOVERY_FAILED"

def test_short_or_noisy_caption_not_fabricated():
    rows, report = fixture()
    rows[1]["text"] = "uh"
    outcome = recover_missing_source_blocks(video_id=VID,timeline_report=report,
        transcript_rows=rows,chat=chat,model="local")
    assert not outcome["complete_evidence_coverage"]
    assert outcome["recovery"]["unrecovered"][0]["reason"] == "NO_USABLE_SOURCE_QUOTE"

def test_already_grounded_report_has_no_model_calls():
    rows, report = fixture()
    report["blocks"][1]["topics"][0]["evidence"] = Q2
    outcome = recover_missing_source_blocks(video_id=VID,timeline_report=report,
        transcript_rows=rows,chat=lambda *a,**k:1/0,model="local")
    assert outcome["complete_evidence_coverage"]
    assert outcome["recovery"]["model_calls"] == 0

def test_retry_cap_rejects_unbounded_attempts():
    import pytest
    rows, report = fixture()
    with pytest.raises(ValueError,match="INVALID_RECOVERY_ATTEMPTS"):
        recover_missing_source_blocks(video_id=VID,timeline_report=report,
            transcript_rows=rows,chat=chat,model="local",max_attempts=5)


def test_second_attempt_uses_different_source_quote():
    rows, report = fixture()
    rows.append({"text": "People in our schools also request additional safety measures this year.",
                 "start": 31.0, "duration": 2.0})
    prompts = []
    def conditional_chat(messages, **kw):
        prompts.append(messages[-1]["content"])
        if len(prompts) == 1:
            return '{"topic":"","summary_uk":""}'
        return json.dumps({"topic":"Безпека шкіл",
                           "summary_uk":"Співрозмовник розмірковує про заходи безпеки у школах."})
    outcome = recover_missing_source_blocks(video_id=VID,timeline_report=report,
        transcript_rows=rows,chat=conditional_chat,model="local",max_attempts=2)
    assert outcome["complete_evidence_coverage"]
    assert outcome["recovery"]["model_calls"] == 2
    assert prompts[0] != prompts[1]
    assert outcome["publication_allowed"] is False
