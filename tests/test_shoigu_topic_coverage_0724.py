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
    assert "max_topic_bullets=24" in block
    assert "max_body_bytes=3500" in block
    assert "max_topic_bullets=2" not in block
    assert "bool(omitted_topics)" in block


def test_if_platform_budget_too_small_omitted_topics_are_explicit():
    report = {"blocks": [{"topics": [{"topic": "Підтверджена важлива тема " + str(i)}]}
                         for i in range(30)]}
    source = "Початковий опис, який не можна стирати. " * 25
    result, omitted = preserve_outline_topics(
        source, report, max_topic_bullets=24, max_body_bytes=350,
    )
    assert result.startswith(source)
    assert len(omitted) > 0
    assert all(item not in result for item in omitted)
