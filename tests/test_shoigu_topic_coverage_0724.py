"""Real operator regression: Shoigu review showed four omitted grounded subjects.

One concise summary is allowed, but 6 grounded topics must not silently
be reduced to two bullets when the description has adequate platform space.
"""
from pathlib import Path

from rg_youtube_control.dialogue_seo import preserve_outline_topics


def test_shoigu_six_grounded_subjects_survive_description_postprocessing():
    topics = [
        "Причина звільнення Шойгу",
        "Корупція в російській армії",
        "Стратегія неадекватності Шойгу",
        "Дискусія про звільнення Шойгу",
        "Корупція та відповідальність",
        "Путін і кадрове рішення",
    ]
    report = {"blocks": [
        {"start_stamp": "00:00:00", "topics": [
            {"topic": topics[0]},
            {"topic": topics[1]},
            {"topic": topics[2]},
        ]},
        {"start_stamp": "00:05:03", "topics": [
            {"topic": topics[3]},
            {"topic": topics[4]},
            {"topic": topics[5]},
        ]},
    ]}
    concise = (
        "Співрозмовники обговорюють зміну посади Шойгу та можливі причини "
        "кадрового рішення. Позиції учасників подано як припущення, а не факти."
    )
    description, omitted = preserve_outline_topics(
        concise, report, max_topic_bullets=24, max_body_bytes=3500,
    )
    assert omitted == []
    assert description.startswith(concise)
    for topic in topics:
        assert topic in description
    assert description.count("• ") == len(topics)
    assert len(description.encode("utf-8")) <= 3500


def test_full_generator_no_longer_limits_topic_retention_to_two():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    block = source.split("def generate_seo_package_local(", 1)[1].split(
        "\ndef _comment_reply_safe_novelty_ok(", 1
    )[0]
    assert "max_topic_bullets=50" in block
    assert "max_body_bytes=3500" in block
    assert "max_topic_bullets=2," not in block
    assert "bool(omitted_topics)" in block


def test_if_platform_budget_too_small_omitted_topics_are_explicit():
    report = {"blocks": [{"topics": [{"topic": "Підтверджена важлива тема " + str(i)}]}
                         for i in range(30)]}
    source = "Початковий опис, який не можна стирати. " * 25
    result, omitted = preserve_outline_topics(
        source, report, max_topic_bullets=24, max_body_bytes=350,
    )
    assert result.startswith(source.strip())
    assert len(omitted) > 0
    assert all(item not in result for item in omitted)


def test_real_preview_repeated_strategy_ab_titles_trigger_review():
    from rg_youtube_control.dialogue_seo import ab_title_issues

    actual = [
        "Шойгу и Путин: почему увольнение стало частью стратегии",
        "Стратегия без Шойгу: как война переходит в новую фазу",
        "Коррупция или стратегия: что стоит за увольнением",
    ]
    reasons = ab_title_issues(actual)
    assert any("Усі три A/B назви повторюють" in x for x in reasons), reasons


def test_distinct_verified_subjects_do_not_trigger_common_story_gate():
    from rg_youtube_control.dialogue_seo import ab_title_issues

    independent = [
        "Шойгу покинул Минобороны: что решили власти России?",
        "Коррупция в армии: что говорят россияне о чиновниках?",
        "Реакция на Путина: почему собеседник изменил мнение?",
    ]
    assert not any("Усі три A/B назви повторюють" in x for x in ab_title_issues(independent))


def test_title_claim_must_be_grounded_in_quotes_not_model_summary():
    from rg_youtube_control.dialogue_seo import ab_title_issues
    report = {"blocks": [
        {"start_stamp": "00:00:00", "topics": [{
            "topic": "Шойгу, корупція, війна переходить у нову фазу",
            "summary_uk": "Вигаданий машинний висновок: війна переходить у нову фазу",
            "evidence": "Он с Путиным в хороших отношениях, а коррупция в армии была всегда.",
        }]},
        {"start_stamp": "00:05:03", "topics": [{
            "topic": "Зміна посади Шойгу",
            "summary_uk": "Припущення учасника про кадри",
            "evidence": "Всё идёт по плану. А сейчас новый министр больше по финансам.",
        }]},
    ]}
    actual_bad = [
        "Шойгу и Путин: почему увольнение стало частью стратегии",
        "Стратегия без Шойгу: как война переходит в новую фазу",
        "Коррупция или стратегия: что стоит за увольнением",
    ]
    warnings = ab_title_issues(actual_bad, report)
    assert any("A/B варіант 2 містить кілька формулювань" in x for x in warnings), warnings
    assert any("Усі три A/B назви повторюють" in x for x in warnings), warnings
