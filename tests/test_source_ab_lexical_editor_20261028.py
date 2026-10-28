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
