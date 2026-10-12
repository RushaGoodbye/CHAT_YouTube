"""Evidence grouping regression tests: no repeated or invented stories."""
from rg_youtube_control.dialogue_seo import (
    distinct_evidence_topics, evidence_outline_text,
)


def test_duplicate_quotes_count_as_one_story():
    quote = "Он с Путиным в хороших отношениях, а коррупция в армии была всегда."
    report = {"blocks": [
        {"start_stamp": "00:00:00", "verified": True,
         "topics": [{"topic": "Шойгу", "evidence": quote,
                     "summary_uk": "Обговорення зв'язків Шойгу"}]},
        {"start_stamp": "00:05:00", "verified": True,
         "topics": [{"topic": "Корупція і зв'язки", "evidence": quote,
                     "summary_uk": "Та сама цитата іншими словами"}]},
    ]}
    assert len(distinct_evidence_topics(report)) == 1
    assert evidence_outline_text(report).count("ЦИТАТА:") == 1


def test_distinct_quotes_retained_and_unverified_visible():
    report = {"blocks": [
        {"start_stamp": "00:00:00", "verified": True,
         "topics": [{"topic": "Корупція", "evidence":
                     "Коррупция в армии была всегда и это проблема.",
                     "summary_uk": "Думка про корупцію"}]},
        {"start_stamp": "00:05:00", "verified": True,
         "topics": [{"topic": "Кадрові зміни", "evidence":
                     "Теперь новый министр занимается вопросами финансов.",
                     "summary_uk": "Обговорюють зміну міністра"}]},
        {"start_stamp": "00:10:00", "verified": False,
         "topics": [], "excerpt": "нерозбірливий фрагмент"},
    ]}
    assert len(distinct_evidence_topics(report)) == 2
    outline = evidence_outline_text(report)
    assert outline.count("ЦИТАТА:") == 2
    assert "НЕПЕРЕВІРЕНИЙ ФРАГМЕНТ" in outline


def test_unverified_model_claims_never_become_source():
    report = {"blocks": [{"verified": False, "start_stamp": "00:00:00",
       "topics": [{"topic": "Вигадана подія",
                   "evidence": "Ніде не підтверджений вислів"}],
       "excerpt": "частковий текст"}]}
    assert distinct_evidence_topics(report) == []
    assert "Вигадана подія" not in evidence_outline_text(report)


def test_recovery_brief_does_not_invent_third_story():
    from rg_youtube_control.free_tools import _ab_distinct_evidence_brief
    quote = "Это одна и та же история, повторённая несколько раз подряд."
    report = {"blocks": [
        {"verified": True, "start_stamp": "00:00:00",
         "topics": [{"topic": "Перший сюжет", "evidence": quote}]},
        {"verified": True, "start_stamp": "00:10:00",
         "topics": [{"topic": "Перефразована назва", "evidence": quote}]},
    ]}
    brief = _ab_distinct_evidence_brief(report)
    assert brief.count("ЦИТАТА:") == 1
    assert "C:" not in brief


def test_recovery_brief_retains_three_distinct_quoted_anchors():
    from rg_youtube_control.free_tools import _ab_distinct_evidence_brief
    report = {"blocks": [
        {"verified": True, "start_stamp": f"00:0{i}:00",
         "topics": [{"topic": f"Сюжет {i}", "evidence": quote}]}
        for i, quote in enumerate((
            "Говорят о коррупции в министерстве и работе чиновников.",
            "Говорят о нехватке топлива и высоких ценах на бензин.",
            "Говорят о религии и отношении к церковным традициям.",
        ))
    ]}
    brief = _ab_distinct_evidence_brief(report)
    assert brief.count("ЦИТАТА:") == 3
