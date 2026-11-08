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
