"""Regression: choose independent grounded A/B topics, not the first three.

No external API, production writes, transcript disclosure or model calls.
"""
from rg_youtube_control.free_tools import _verified_source_ab_titles
from rg_youtube_control.dialogue_seo import ab_title_issues


def _block(topic, evidence, verified=True):
    return {"verified": verified, "topics": [
        {"topic": topic, "summary_uk": "Підтверджена розмова про тему.",
         "evidence": evidence}
    ]}


def test_select_three_distinct_verified_subjects_instead_of_first_three():
    report = {"blocks": [
        _block("Корупція", "Они обсуждали коррупцию и власть чиновников"),
        _block("Корупція в обороні", "Коррупция в обороне и проверки, обсуждали всё"),
        _block("Корупція посадовців", "Коррупция должностных лиц в министерстве"),
        _block("Бензин", "Бензин на заправке вырос в цене сегодня"),
        _block("Мобілізація", "Мобилизация продолжается в регионе, об этом говорили"),
    ]}
    proposals = _verified_source_ab_titles(report, "Заголовок відео")
    assert len(proposals) == 3, proposals
    assert sum("Корупція" in title for title in proposals) == 1, proposals
    assert any("Бензин" in title for title in proposals), proposals
    assert any("Мобілізація" in title for title in proposals), proposals
    assert ab_title_issues(proposals, report) == []


def test_unverified_sources_cannot_fill_missing_third_hook():
    report = {"blocks": [
        _block("Корупція", "Они обсуждали коррупцию и власть чиновников"),
        _block("Бензин", "Бензин на заправке вырос в цене сегодня"),
        _block("Мобілізація", "Мобилизация продолжается в регионе", verified=False),
    ]}
    proposals = _verified_source_ab_titles(report, "Заголовок відео")
    assert len(proposals) == 3
    assert "Корупція та Бензин" in proposals[2]
    assert all("Мобілізація" not in title for title in proposals)
    assert not ab_title_issues(proposals, report)


def test_model_only_subject_does_not_become_verified_source():
    report = {"blocks": [
        _block("Психологія сім'ї", "Они обсуждали коррупцию и власть чиновников"),
        _block("Бензин", "Бензин на заправке вырос в цене сегодня"),
        _block("Мобілізація", "Мобилизация продолжается в регионе"),
    ]}
    proposals = _verified_source_ab_titles(report, "Заголовок відео")
    assert all("Психологія" not in title for title in proposals)


def test_two_non_dictionary_topics_still_allow_source_verified_third_angle():
    report = {"blocks": [
        _block("Культура", "Культура здесь обсуждалась очень подробно"),
        _block("Бюджет", "Бюджет региона обсуждали в другой беседе"),
    ]}
    titles = _verified_source_ab_titles(report, "Стара назва")
    assert len(titles) == 3, titles
    assert "Культура та Бюджет" in titles[2], titles
    assert ab_title_issues(titles, report) == []


def test_single_quoted_story_never_claims_three_independent_topics():
    report = {"blocks": [
        _block("Корупція", "Коррупция чиновников обсуждалась долго"),
    ]}
    assert len(_verified_source_ab_titles(report, "Стара назва")) == 1
