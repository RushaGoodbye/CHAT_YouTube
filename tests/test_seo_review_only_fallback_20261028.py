"""Real regression: keep an evidence-grounded review draft without inventing tags."""

import json

from rg_youtube_control import free_tools as ft
from rg_youtube_control.seo_readiness import ready_for_youtube


REPORT = {
    "blocks_total": 1,
    "blocks_with_evidence": 1,
    "blocks": [{
        "verified": True,
        "start_stamp": "00:00:00",
        "topics": [
            {"topic": "корупція", "evidence": "Шойгу коррупция и оборона"},
            {"topic": "непевна автоматична мітка", "evidence": "Неизвестный фрагмент распознавания"},
        ],
    }],
}


def test_unknown_asr_subject_is_not_published_or_lost():
    unmapped = []
    description = ft._deterministic_evidence_description(
        "Шойгу", REPORT, review_unmapped=unmapped,
    )
    assert "корупція" in description
    assert len(unmapped) == 1
    assert "непевна автоматична мітка" not in description


def test_partial_ab_and_sparse_tags_remain_review_draft(monkeypatch):
    calls = []
    def model(*args, **kwargs):
        calls.append("model")
        return json.dumps({
            "title": "Шойгу: корупція і зміна посади?",
            "title_variants": [
                "Шойгу та корупція: що розповіли співрозмовники?",
                "Причини кадрових змін: думки росіян про Шойгу",
            ],
            "description": "Думки співрозмовників про Шойгу та корупцію.",
            "tags": [],
            "chapters": "",
        }, ensure_ascii=False)
    monkeypatch.setattr(ft, "ollama_chat", model)
    monkeypatch.setattr(ft, "_recover_title_variants", lambda **kwargs: [])
    monkeypatch.setattr(ft, "_recover_independent_ab_titles", lambda **kwargs: [])
    monkeypatch.setattr(ft, "_source_quote_ab_titles", lambda *args: [])
    result = ft.generate_seo_package_local(
        current_title="Шойгу і корупція",
        transcript="Шойгу коррупция и оборона",
        evidence_report=REPORT,
        is_short=True,
        timeout=1,
    )
    assert result["needs_review"] is True
    assert result["youtube_data_api_quota"] == 0
    assert result["description"]
    assert len(result["title_variants"]) <= 2
    assert "Частину цитованих тем" in result["review_reason"]
    ok, reasons = ready_for_youtube(
        status="draft", generation="local-seo-real",
        quality_state="needs_review", variants=result["title_variants"],
    )
    assert ok is False and reasons
    assert len(calls) == 1
