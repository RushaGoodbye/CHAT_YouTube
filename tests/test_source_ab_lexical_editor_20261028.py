"""Source-anchored Ukrainian A/B fallback, no invented plots or auto-publish."""
from __future__ import annotations

from rg_youtube_control.source_ab_lexical import source_grounded_ukrainian_ab
from rg_youtube_control.dialogue_seo import ab_title_issues


def _block(*quotes, verified=True):
    return {"verified": verified, "topics": [
        {"topic": "Дослівно", "summary_uk": "Розмова про підтверджені теми.",
         "evidence": q}
        for q in quotes
    ]}


def test_falls_back_to_only_real_source_subjects():
    report = {"blocks": [
        _block("Вопросы коррупции чиновников обсуждали сегодня в беседе"),
        _block("Война продолжается, но речь была и про мобилизацию"),
        _block("Бензин в регионе стал дороже и цены обсуждают опять"),
    ]}
    names = source_grounded_ukrainian_ab(report, "Стара назва")
    assert len(names) == 3, names
    assert not ab_title_issues(names, report), (names, ab_title_issues(names, report))
    assert any("Корупція" in name for name in names)
    assert any("Бензин" in name or "Мобілізація" in name for name in names)
    assert all(not any(word in name for word in ("Звільнили", "Знищили", "Перемогли"))
               for name in names)


def test_ignores_unverified_dramatic_story():
    report = {"blocks": [
        _block("Никто не обсуждал военные перевороты или сенсации", verified=False),
        _block("Бензин в регионе стал дороже и цены обсуждают опять"),
        _block("Вопросы коррупции чиновников обсуждали сегодня в беседе"),
    ]}
    result = source_grounded_ukrainian_ab(report)
    assert all("Війна" not in s for s in result)


def test_requires_three_real_distinct_topics_no_padding():
    report = {"blocks": [
        _block("Бензин на заправке снова обсуждали в разговоре"),
        _block("В разговоре был бензин и только бензин на АЗС"),
        _block("Бензин сейчас обсуждают многие собеседники"),
    ]}
    assert source_grounded_ukrainian_ab(report) == []


def test_does_not_use_model_topic_labels_as_source():
    report = {"blocks": [
        {"verified": True, "topics": [
            {"topic": "Вибух атомної станції", "summary_uk": "Вигадана подія",
             "evidence": "Говорили о бензине на заправке и цене"}
        ]},
        _block("Коррупция чиновников обсуждалась в разговоре"),
        _block("Мобилизация в регионе была темой разговора"),
    ]}
    names = source_grounded_ukrainian_ab(report)
    assert len(names) == 3, names
    assert all("атомн" not in title.casefold() for title in names)


def test_short_gas_root_does_not_turn_newspaper_into_energy_topic():
    from rg_youtube_control.source_ab_lexical import _grounded_labels
    assert "Газ" not in _grounded_labels("Старая газета рассказывала об истории")
    assert "Газ" in _grounded_labels("Газ на рынке стал дороже")


def test_two_distinct_verified_sources_produce_three_review_angles():
    report = {"blocks": [
        _block("Коррупция чиновников обсуждалась на встрече"),
        _block("Бензин на заправках подорожал в регионе"),
    ]}
    proposals = source_grounded_ukrainian_ab(report, "Стара назва")
    assert len(proposals) == 3, proposals
    assert any("Корупція" in title for title in proposals)
    assert any("Бензин" in title for title in proposals)
    assert "Корупція та Бензин" in proposals[2], proposals
    assert ab_title_issues(proposals, report) == []


def test_two_topics_in_one_quotation_cannot_fake_two_independent_sources():
    report = {"blocks": [
        _block("Бензин и коррупция обсуждались вместе в одной реплике"),
    ]}
    assert source_grounded_ukrainian_ab(report, "Стара назва") == []


def test_unverified_second_source_does_not_unlock_three_titles():
    report = {"blocks": [
        _block("Коррупция чиновников обсуждалась на встрече"),
        _block("Бензин на заправках подорожал в регионе", verified=False),
    ]}
    assert source_grounded_ukrainian_ab(report) == []


def test_quoted_word_diversity_recovers_topics_obscured_by_repeated_lead():
    report = {"blocks": [
        _block("Коррупция и мобилизация обсуждались в разговоре"),
        _block("Коррупция и бензин обсуждались в следующей беседе"),
        _block("Коррупция и санкции обсуждались в третьем разговоре"),
    ]}
    titles = source_grounded_ukrainian_ab(report)
    assert len(titles) == 3, titles
    assert not ab_title_issues(titles, report), titles
    assert len({
        title.split(":", 1)[0].casefold()
        for title in titles
    }) == 3


def test_three_subject_words_from_one_quote_are_not_three_evidence_stories():
    report = {"blocks": [
        _block("Коррупция, мобилизация и бензин перечислены в одной фразе"),
    ]}
    assert source_grounded_ukrainian_ab(report) == []


def test_two_independent_quotes_with_overlapping_words_yield_review_angles():
    report = {"blocks": [
        _block("Коррупция и мобилизация обсуждались в разговоре"),
        _block("Коррупция и бензин обсуждались в следующей беседе"),
    ]}
    titles = source_grounded_ukrainian_ab(report)
    assert len(titles) == 3, titles
    assert not ab_title_issues(titles, report), titles
