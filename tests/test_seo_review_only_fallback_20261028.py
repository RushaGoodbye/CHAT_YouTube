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


def test_exhausted_local_model_preserves_read_only_draft(monkeypatch):
    def model_fails(*args, **kwargs):
        raise RuntimeError("Ollama local model did not return a valid package")
    monkeypatch.setattr(ft, "ollama_chat", model_fails)
    result = ft.generate_seo_package_local(
        current_title="Шойгу та корупція",
        transcript="Шойгу коррупция и оборона",
        evidence_report=REPORT,
        is_short=True,
        timeout=1,
    )
    assert result["needs_review"] is True
    assert result["title"] == "Шойгу та корупція"
    assert len(result["title_variants"]) <= 1
    assert "непублікаційний" in result["review_reason"]
    assert result["youtube_data_api_quota"] == 0
    ok, _ = ready_for_youtube(
        status="draft", generation="local-seo-real",
        quality_state="needs_review", variants=result["title_variants"],
    )
    assert not ok


def test_model_failure_without_verified_quotes_is_still_blocked(monkeypatch):
    import pytest
    monkeypatch.setattr(ft, "ollama_chat", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(ValueError, match="Локальна SEO-генерація"):
        ft.generate_seo_package_local(
            current_title="Шойгу", transcript="невідомо",
            evidence_report={"blocks": []}, is_short=True, timeout=1,
        )


def test_two_verified_topics_generate_three_distinct_angles(monkeypatch):
    report = {
        "blocks": [
            {"verified": True, "start_stamp": "00:00:00", "topics": [{
                "topic": "корупція", "evidence": "Шойгу коррупция в Министерстве обороны, об этом говорят россияне",
            }]},
            {"verified": True, "start_stamp": "00:06:00", "topics": [{
                "topic": "стратегія", "evidence": "Шойгу и МЧС, война это война и нужна другая стратегия",
            }]},
        ]
    }
    responses = iter([
        {"title": "Шойгу та корупція: що розповіли співрозмовники?"},
        {"title": "Шойгу та МНС: як обговорювали військову стратегію?"},
        {"title": "Зміна посади Шойгу: чому згадували корупцію?"},
    ])
    monkeypatch.setattr(ft, "ollama_chat", lambda *args, **kwargs:
                        json.dumps(next(responses), ensure_ascii=False))
    titles = ft._recover_independent_ab_titles(
        report=report, current_title="Шойгу", model="mock",
    )
    assert len(titles) == 3
    assert len(set(title.casefold() for title in titles)) == 3


def test_source_verified_ukrainian_titles_are_generic_review_proposals():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "корупція", "evidence": "Шойгу коррупция в министерстве"},
        {"topic": "посада", "evidence": "Шойгу поменял должность после кадрового решения"},
        {"topic": "Путін", "evidence": "Шойгу Путин обсудили положение"},
    ]}]}
    titles = ft._verified_source_ab_titles(report, "Шойгу")
    assert len(titles) == 3
    assert all(20 <= len(title) <= 100 for title in titles)
    assert all(not any(c in title for c in "ыэъё") for title in titles)
    assert not ft._verified_source_ab_titles({"blocks": []}, "Шойгу")


def test_source_fallback_works_for_entirely_different_video_topics():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "бензин", "evidence": "На АЗС бензин подорожал, автомобилисты спорят"},
        {"topic": "зарплати", "evidence": "Люди говорят о зарплатах и доходах"},
        {"topic": "пенсії", "evidence": "Какие сейчас пенсии у жителей региона"},
    ]}]}
    titles = ft._verified_source_ab_titles(report, "Ціни на пальне")
    assert len(titles) == 3
    assert "бензин" in titles[0].casefold()
    assert "зарплати" in titles[1].casefold()
    assert "пенсії" in titles[2].casefold()


def test_fallback_never_uses_unverified_or_unrelated_model_labels():
    report = {"blocks": [
        {"verified": False, "topics": [
            {"topic": "сенсація", "evidence": "Сенсация в космосе"},
        ]},
        {"verified": True, "topics": [
            {"topic": "сімейна психологія", "evidence": "На АЗС бензин дорожает"},
            {"topic": "бензин", "evidence": "На АЗС бензин дорожает"},
        ]},
    ]}
    titles = ft._verified_source_ab_titles(report, "Бензин")
    assert len(titles) == 1
    assert "психолог" not in titles[0]


def test_verified_topic_fallback_rejects_one_supported_word_hiding_false_claim():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "Бензин та секретні космічні документи",
         "evidence": "Бензин на заправці дорожчає, говорять водії."},
        {"topic": "Корупція",
         "evidence": "Коррупция в министерстве это тема"},
    ]}]}
    choices = ft._verified_source_ab_titles(report, "Бензин")
    assert not any("космічн" in item for item in choices)


def test_fallback_is_review_only_even_with_three_grounded_titles(monkeypatch):
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "Корупція", "evidence": "Коррупция чиновников обсуждалась"},
        {"topic": "Бензин", "evidence": "Бензин на заправке сильно подорожал"},
        {"topic": "Мобілізація", "evidence": "Мобилизация людей в разных регионах"},
    ]}]}
    monkeypatch.setattr(ft, "ollama_chat", lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError("model offline")))
    package = ft.generate_seo_package_local(
        current_title="Бензин, корупція та мобілізація",
        transcript="Бензин на заправке подорожал. Коррупция чиновников. Мобилизация людей.",
        evidence_report=report, timeout=1, fast_mode=False,
    )
    assert package["needs_review"] is True
    assert package["youtube_data_api_quota"] == 0
    assert package["provider"].startswith("ollama:")
    assert len(package["title_variants"]) == 3
