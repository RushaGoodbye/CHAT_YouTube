"""Regression for bounded, quote-only fallback after failed model extraction."""
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks


def _empty_model(*args, **kwargs):
    return '{"topics":[]}'


def test_fallback_recovers_only_literal_grounded_topic(tmp_path):
    rows = [{"start": 0, "duration": 3,
             "text": "Коррупция чиновников обсуждалась в разговоре подробно."}]
    report = analyze_all_timeline_blocks(
        rows, model="offline", chat=_empty_model, cache_dir=tmp_path,
    )
    assert report["blocks_with_evidence"] == 1
    item = report["blocks"][0]["topics"][0]
    assert item["topic"] == "Корупція"
    assert item["evidence"] == rows[0]["text"]
    assert "згадується" in item["summary_uk"]


def test_fallback_does_not_fabricate_topics_without_source_word(tmp_path):
    rows = [{"start": 0, "duration": 2,
             "text": "Добрий день, як ваші справи, дякую за розмову."}]
    report = analyze_all_timeline_blocks(
        rows, model="offline", chat=_empty_model, cache_dir=tmp_path,
    )
    assert report["blocks_with_evidence"] == 0
    assert report["unverified_blocks"] == [1]


def test_fallback_never_accepts_unverified_model_claim(tmp_path):
    rows = [{"start": 0, "duration": 3,
             "text": "Бензин на заправках був темою розмови сьогодні."}]
    report = analyze_all_timeline_blocks(
        rows, model="offline", chat=_empty_model, cache_dir=tmp_path,
    )
    assert report["blocks_with_evidence"] == 1
    assert report["blocks"][0]["topics"][0]["topic"] == "Бензин"
