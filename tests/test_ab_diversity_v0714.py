"""Regression for different A/B stories on real 50-minute dialogues."""
from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.free_tools import _ab_distinct_evidence_brief


def test_real_50minute_ab_titles_are_the_same_story():
    variants = [
        "ПОХОВАВ ДРУЗІВ І ПИТАЄТЬСЯ: ЧИ ВСІ ВІДДАЛИ ЖИТТЯ?",
        "ПОХОВАВ ДРУЗІВ І НЕ ВІДПОВІДАЄ: ЧИ ВІДДАЛИ ВОНИ ЖИТТЯ?",
        "ПОХОВАВ ДРУЗІВ І ПИТАЄТЬСЯ: ЧИ ВІДДАЛИ ВОНИ ЖИТТЯ ЗА РОСІЮ?",
    ]
    problems = ab_title_issues(variants)
    assert any("повторюють один сюжетний гачок" in issue for issue in problems)


def test_three_different_supported_angles_are_not_marked_duplicates():
    variants = [
        "ПОХОВАЛ ДРУЗЕЙ НА ВОЙНЕ - ЗА ЧТО ОНИ ПОГИБЛИ?",
        "СТРАХ И МОЛЧАНИЕ: ПОЧЕМУ РОССИЯНЕ НЕ ГОВОРЯТ О ВОЙНЕ?",
        "БЕНЗИН В ВОЛГОГРАДЕ: ЧТО РАССКАЗАЛИ О ЦЕНАХ?",
    ]
    assert not any(
        "повторюють один сюжетний гачок" in issue
        for issue in ab_title_issues(variants)
    )


def test_evidence_recovery_hints_sample_early_middle_late():
    blocks = []
    for i in range(9):
        blocks.append({
            "start_stamp": f"00:{i * 5:02d}:00",
            "topics": [{
                "topic": f"Подія {i} та позиція співрозмовника",
                "evidence": f"Пряма цитата {i} з розмови",
            }],
        })
    hint = _ab_distinct_evidence_brief({"blocks": blocks})
    assert "Подія 0 " in hint
    assert "Подія 4 " in hint
    assert "Подія 8 " in hint
    assert hint.count("ЦИТАТА:") == 3


def test_unsupported_topic_without_quote_is_not_recovery_evidence():
    report = {"blocks": [
        {"topics": [{"topic": "Сімейна психологія", "evidence": ""}]},
        {"topics": [{"topic": "Економічна криза", "evidence": ""}]},
        {"topics": [{"topic": "Політика", "evidence": ""}]},
    ]}
    assert _ab_distinct_evidence_brief(report) == ""


def test_never_fabricate_three_topics_from_one_evidence_block():
    report = {"blocks": [
        {"start_stamp": "00:00", "topics": [{
            "topic": "Одна підтверджена тема", "evidence": "Одна цитата"
        }]}
    ]}
    hint = _ab_distinct_evidence_brief(report)
    assert hint.count("ЦИТАТА:") == 1
    assert "B:" not in hint and "C:" not in hint
