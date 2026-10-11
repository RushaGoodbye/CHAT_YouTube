"""Regression checks from the first real 50-minute 0.7.12 SEO QA."""
from pathlib import Path

from rg_youtube_control.dialogue_seo import preserve_outline_topics
from rg_youtube_control.free_tools import _chapters_are_generic
from rg_youtube_control.optimization import safe_description_fix


def test_long_timeline_keeps_six_topics_not_twenty_in_description():
    report = {"blocks": [
        {"topics": [{"topic": f"Тема {i:02d} - конкретне питання розмови"}]}
        for i in range(21)
    ]}
    description, omitted = preserve_outline_topics(
        "Розмова про відповідальність за війну.",
        report,
        max_body_bytes=3900,
    )
    assert description.count("• ") == 6
    assert "Тема 00" in description
    assert "Тема 20" in description
    assert "Тема 08" in description
    assert "Тема 12" in description
    assert len(omitted) == 15
    assert all(topic not in description for topic in omitted)


def test_short_verified_timeline_preserves_all_distinct_topics():
    report = {"blocks": [
        {"topics": [{"topic": f"Тема {i} і її обговорення"}]}
        for i in range(4)
    ]}
    description, omitted = preserve_outline_topics("Відео про обговорення.", report)
    assert description.count("• ") == 4
    assert omitted == []


def test_generic_chapters_from_real_video_are_rejected():
    chapters = (
        "00:00:00 Початок розмови\n"
        "00:10:04 Розвиток головної теми\n"
        "00:25:08 Думки співрозмовників\n"
        "00:35:11 Подальше обговорення\n"
        "00:45:16 Підсумок розмови"
    )
    assert _chapters_are_generic(chapters)


def test_final_metadata_adds_three_hashtags_and_canonical_links():
    description = safe_description_fix(
        "Співрозмовник обговорює війну та відповідальність.",
        "Росіяни про війну і втрати",
    ).after
    assert "links.rginfoua.pp.ua" in description
    assert "donate.rginfoua.pp.ua" in description
    assert len([token for token in description.split() if token.startswith("#")]) == 3


def test_generator_marks_unchanged_title_and_discards_generic_chapters():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    function = source.split("def generate_seo_package_local(", 1)[1].split(
        "\ndef _comment_reply_safe_novelty_ok(", 1
    )[0]
    assert '"title_unchanged": unchanged_title' in function
    assert 'or unchanged_title' in function
    assert 'if chapters and _chapters_are_generic(chapters):' in function
    assert 'if fast_mode and chapters and _chapters_are_generic(chapters):' not in function
