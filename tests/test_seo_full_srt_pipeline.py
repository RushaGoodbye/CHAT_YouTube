"""Source traceability requirements of the universal full-SRT SEO pipeline."""
import json
import pytest

from rg_youtube_control.seo_full_srt_topics import analyze_full_original_transcript
from rg_youtube_control.seo_full_srt_pipeline import source_packet_from_complete_map

VID="Z7AhB4mjvlM"


def rows(n=18):
    return [{"start":float(i*4), "duration":3,
             "text":f"Діалог {i}: розповідь учасника про перевірку реальних слів і контексту відео"}
            for i in range(n)]


def grounded_chat(messages):
    inp=json.loads(messages[-1]["content"])
    cue=inp["cues"][len(inp["cues"])//2]
    return json.dumps({"topics":[
        {"source_index":cue["source_index"],"quote":cue["text"],
         "label_uk":"Розмова про перевірку контексту","kind":"speech"}
    ]},ensure_ascii=False)


def test_one_grounded_topic_from_each_full_source_window():
    original=rows()
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert len(packet["records"])==full["window_count"]
    assert packet["full_srt_cues_processed"]==18
    assert packet["full_srt_windows_processed"]==full["window_count"]
    assert packet["publication_allowed"] is False
    assert packet["contains_provisional_sources"] is True
    starts=[r["start_s"] for r in packet["records"]]
    assert starts==sorted(starts)


def test_missing_full_window_topic_is_reported_not_silent():
    original=rows()
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    full["topic_records_review_only"]=full["topic_records_review_only"][:-1]
    with pytest.raises(ValueError,match="UNDOCUMENTED_TOPICAL_WINDOW"):
        source_packet_from_complete_map(
            video_id=VID,original_rows=original,full_map=full,max_chars=600)


def test_model_topic_cannot_claim_quote_not_found_in_original():
    original=rows()
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    full["topic_records_review_only"][0]["source_quote"]="Вигадана цитата"
    with pytest.raises(ValueError,match="FULL_MAP_QUOTE_NOT_IN_SOURCE"):
        source_packet_from_complete_map(
            video_id=VID,original_rows=original,full_map=full,max_chars=600)


def test_source_coverage_falsification_rejected():
    original=rows()
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    full["source_cues_processed"]=4
    with pytest.raises(ValueError,match="FULL_SOURCE_COVERAGE_REQUIRED"):
        source_packet_from_complete_map(
            video_id=VID,original_rows=original,full_map=full,max_chars=600)


def test_secondary_source_topics_are_included_without_losing_later_windows():
    original=rows(24)
    def two_topics(messages):
        inp=json.loads(messages[-1]["content"])
        candidates=inp["cues"]
        return json.dumps({"topics":[{
            "source_index":cue["source_index"], "quote":cue["text"],
            "label_uk":"Розмова про перевірку контексту", "kind":"speech"
        } for cue in candidates[:2]]},ensure_ascii=False)
    full=analyze_full_original_transcript(original,chat=two_topics,max_chars=600)
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert packet["source_topics_selected"] > full["window_count"]
    assert packet["source_topics_selected"] <= 12
    assert packet["source_topic_candidates_total"] >= packet["source_topics_selected"]
    assert packet["source_topics_omitted_from_synthesis"] >= 0
    assert packet["records"][-1]["start_s"] >= full["windows"][-1]["start_s"]
    assert packet["publication_allowed"] is False


def test_long_stream_synthesis_samples_full_timeline_without_falsely_passing():
    original=rows(160)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    assert full["window_count"]>12
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert packet["full_srt_cues_processed"]==160
    assert len(packet["records"])==12
    assert packet["source_windows_in_synthesis"][0]==0
    assert packet["source_windows_in_synthesis"][-1]==full["window_count"]-1
    assert packet["source_windows_omitted_from_synthesis"]
    assert packet["topical_synthesis_complete"] is False
    assert packet["publication_allowed"] is False


def test_short_stream_topic_selection_is_complete():
    original=rows(18)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert packet["topical_synthesis_complete"] is True
    assert packet["source_windows_omitted_from_synthesis"]==[]


def test_short_source_cue_falls_back_to_another_literal_topic_in_same_window():
    original=rows(18)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    first=full["topic_records_review_only"][0]
    short={**first,"source_quote":"Так","topic_candidate_not_fact":"Коротка репліка"}
    full["topic_records_review_only"]=[short,first]+full["topic_records_review_only"][1:]
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert packet["records"][0]["literal_quote"]==first["source_quote"]
    assert packet["topical_synthesis_complete"] is True


def test_all_short_quotes_block_semantic_completion_but_not_video_analysis():
    original=rows(18)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    # The first window has no eligible source quote.
    full["topic_records_review_only"][0]["source_quote"]="Так"
    packet=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,max_chars=600)
    assert 0 in packet["windows_with_only_short_topics"]
    assert packet["topical_synthesis_complete"] is False
    assert packet["publication_allowed"] is False


def test_long_video_highlight_selector_considers_every_topical_window():
    original=rows(160)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    considered=[]
    def selector(messages):
        packet=json.loads(messages[-1]["content"])
        candidates=packet["options"]
        considered.extend(x["window_index"] for x in candidates)
        return json.dumps({"source_index": candidates[-1]["source_index"]})
    result=source_packet_from_complete_map(
        video_id=VID,original_rows=original,full_map=full,
        max_chars=600,selector=selector)
    assert result["source_topics_selected"]==12
    assert result["topical_synthesis_complete"] is True
    assert result["all_topical_windows_considered_for_highlights"] is True
    assert set(considered)==set(range(full["window_count"]))
    assert result["source_windows_omitted_from_synthesis"]
    assert result["publication_allowed"] is False
    for rec in result["records"]:
        assert any(row["text"]==rec["literal_quote"] for row in original)


def test_highlight_selector_rejects_invented_source_index():
    original=rows(160)
    full=analyze_full_original_transcript(original,chat=grounded_chat,max_chars=600)
    with pytest.raises(ValueError,match="HIGHLIGHT_SELECTOR_NOT_IN_SOURCE"):
        source_packet_from_complete_map(
            video_id=VID,original_rows=original,full_map=full,
            max_chars=600,selector=lambda _: json.dumps({"source_index":999999}))
