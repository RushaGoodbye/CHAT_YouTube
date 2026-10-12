"""Real Shoigu 9:53 regression. No more one-off installer until this is green."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.dialogue_seo import preserve_outline_topics
from rg_youtube_control.free_tools import (
    _grounded_chapters_from_transcript, _chapters_quality_error,
    transcript_sample_text,
)
from rg_youtube_control.ui import MainWindow


def _six_real_topics():
    titles = (
        "причина увольнения Шойгу",
        "корупція в російській армії",
        "стратегічна неадекватність Шойгу",
        "дискусія про увільнення Шагу",
        "дискусія про причини зміни посади",
        "дискусія про корупцію та відповідальність",
    )
    return {
        "blocks_total": 2,
        "blocks_with_evidence": 2,
        "rows_covered": 165,
        "blocks": [
            {"start_stamp": "00:00:00", "topics": [
                {"topic":t, "evidence":"джерело","summary_uk":t}
                for t in titles[:3]]},
            {"start_stamp": "00:05:03", "topics": [
                {"topic":t, "evidence":"джерело","summary_uk":t}
                for t in titles[3:]]},
        ],
    }


def test_all_six_shoigu_topics_are_preserved_without_arbitrary_two_topic_cap():
    report = _six_real_topics()
    synopsis = (
        "У цьому випуску чат-рулетки співрозмовники обговорюють "
        "перестановки в Міноборони РФ, можливі причини зміни посади "
        "Шойгу, корупційні звинувачення й стратегічну компетентність. "
    ) * 2
    result, omitted = preserve_outline_topics(
        synopsis, report, max_topic_bullets=12, max_body_bytes=3600,
    )
    assert not omitted
    for block in report["blocks"]:
        for topic in block["topics"]:
            assert topic["topic"] in result


def test_shoigu_chapter_fallback_does_not_emit_hardcoded_seven_chapters():
    # Only actual caption timestamp 00:00 and 05:03 are available.
    rows = [{"start":0,"text":"Всё идёт по плану"},
            {"start":303,"text":"Коррупция или всё идёт по плану"}]
    transcript = transcript_sample_text(rows)
    proposal = _grounded_chapters_from_transcript(
        current_title="Увольнение ШОЙГУ - коррупция или план?",
        transcript=transcript,
    )
    assert proposal == ""
    assert "08:11" not in proposal
    assert "Тимур Іванов" not in proposal
    assert _chapters_quality_error(
        "00:00 Початок розмови\n08:11 Тимур Іванов і команда Шойгу",
        transcript,
    ) != ""


def test_existing_rich_shoigu_draft_cannot_be_silently_replaced():
    reasons = MainWindow._seo_candidate_regressions(
        existing_description="Повний SEO-опис про Шойгу. " * 28,
        existing_chapters="\n".join(
            f"{n:02d}:00 Збережена глава {n}" for n in range(7)
        ),
        new_description="Короткий уривок про Шойгу.",
        new_chapters="",
        omitted_topics=["діалог про Міністерство", "питання фінансів"],
        ab_quality_issues=["повторюють один сюжетний гачок"],
    )
    assert len(reasons) >= 3
    assert any("7" in x for x in reasons)
    assert any("підтверджених тем" in x for x in reasons)
    assert any("A/B" in x for x in reasons)


def test_good_new_candidate_has_no_false_regressions():
    reasons = MainWindow._seo_candidate_regressions(
        existing_description="Стислий опис наявного відео.",
        existing_chapters="",
        new_description="Новий змістовний і перевірений опис відео.",
        new_chapters="",
        omitted_topics=[],
        ab_quality_issues=[],
    )
    assert reasons == []
