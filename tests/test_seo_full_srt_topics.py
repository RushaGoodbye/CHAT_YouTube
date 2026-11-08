"""Deterministic contract tests of whole-source coverage and quote integrity."""
import json
import pytest
from rg_youtube_control.seo_full_srt_topics import (
    split_transcript_windows, extract_grounded_window_topics,
    analyze_full_original_transcript,
)


def rows(n=60):
    return [{"start":float(i*5),"duration":4.0,
             "text":f"Розмова {i}: учасник обговорює підтвердження змісту відео у фрагменті"}
            for i in range(n)]


def fake_chat(messages):
    prompt=json.loads(messages[-1]["content"])
    cue=prompt["cues"][-1]
    return json.dumps({"topics":[
        {"source_index":cue["source_index"],"quote":cue["text"],
         "label_uk":"Обговорення змісту відео","kind":"speech"}
    ]},ensure_ascii=False)


def test_covers_all_original_cues_not_just_five():
    original=rows(60)
    windows=split_transcript_windows(original,max_chars=600)
    assert len(windows)>5
    assert sum(x["cue_count"] for x in windows)==60
    assert [c["source_index"] for w in windows for c in w["cues"]]==list(range(60))
    report=analyze_full_original_transcript(original,chat=fake_chat,max_chars=600)
    assert report["window_count"]==len(windows)
    assert report["source_cues_processed"]==60
    assert report["all_nonempty_cues_covered"] is True
    assert len(report["topic_records_review_only"])==len(windows)
    assert report["topic_records_review_only"][-1]["source_index"]>=55
    assert report["publication_allowed"] is False


def test_rejects_model_quote_that_does_not_exist():
    window=split_transcript_windows(rows(3),max_chars=600)[0]
    def hallucination(messages):
        return json.dumps({"topics":[{"source_index":0,
            "quote":"Вигадана цитата","label_uk":"Непідтверджена подія",
            "kind":"report"}]},ensure_ascii=False)
    result=extract_grounded_window_topics(window,chat=hallucination)
    assert result["topics"]==[]
    assert result["rejected"][0]["reason"]=="UNSUPPORTED_WINDOW_TOPIC"


def test_preserves_uncertainty_even_for_exact_quote():
    original=rows(2)
    windows=split_transcript_windows(original,max_chars=600)
    topic=extract_grounded_window_topics(windows[0],chat=fake_chat)["topics"][0]
    assert topic["factual_truth_verified"] is False
    assert topic["speaker_verified"] is False
    assert topic["editorial_verified"] is False


def test_rejects_bad_time_order():
    values=rows(3)
    values[2]["start"]=0
    with pytest.raises(ValueError,match="INVALID_ORIGINAL_CUE_ORDER"):
        split_transcript_windows(values)


def test_no_substantive_topic_is_explicit_not_silent():
    report=analyze_full_original_transcript(rows(20),
        chat=lambda _:json.dumps({"topics":[]}),max_chars=600)
    assert len(report["windows_without_substantive_topics"])==report["window_count"]
    assert report["topic_records_review_only"]==[]
    assert report["needs_review"] is True


def test_close_quote_resolves_to_original_cue_not_model_rewrite():
    original=rows(3)
    window=split_transcript_windows(original,max_chars=600)[0]
    actual=window["cues"][0]
    slightly_changed=actual["text"].replace("відео", "відео.")
    def adjusted(messages):
        return json.dumps({"topics":[{"source_index":actual["source_index"],
            "quote":slightly_changed, "label_uk":"Перевірка змісту відео",
            "kind":"speech"}]},ensure_ascii=False)
    checked=extract_grounded_window_topics(window,chat=adjusted)
    assert len(checked["topics"])==1
    assert checked["topics"][0]["source_quote"]==actual["text"]
    assert checked["topics"][0]["source_quote_restored_from_original"] is True
    assert checked["topics"][0]["factual_truth_verified"] is False
