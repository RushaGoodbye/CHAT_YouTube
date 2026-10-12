"""Real-video regression derived from 2026-10-12 no-write AlexPC Shoigu evidence audit.

This intentionally asserts the current gate DOES NOT call the weak A/B list
publish-ready; phase 2 must improve candidate generation, not bypass this gate.
"""
from rg_youtube_control.dialogue_seo import (
    ab_title_issues, preserve_outline_topics, evidence_outline_text,
)

SHOIGU_REAL_REPORT = {
    "blocks_total": 2,
    "blocks_with_evidence": 2,
    "rows_covered": 165,
    "blocks": [
        {
            "start_stamp": "00:00:00",
            "end_stamp": "00:05:05",
            "topics": [
                {"topic": "причина увольнения Шойгу",
                 "summary_uk": "Співрозмовник припускає причини зміни посади.",
                 "evidence": "он с Путиным в хороших отношениях чтоб отношения не испорти"},
                {"topic": "корупція в російській армії",
                 "summary_uk": "Співрозмовник говорить про звинувачення.",
                 "evidence": "здесь коррупция шагу насколько я помню предъявлены обвинения конкретным лицам"},
                {"topic": "стратегічна неадекватність Шойгу",
                 "summary_uk": "Співрозмовник порівнює МЧС і війну.",
                 "evidence": "я считаю так да потому что МЧС это МЧС А война это война"},
            ],
        },
        {
            "start_stamp": "00:05:03",
            "end_stamp": "00:09:34",
            "topics": [
                {"topic": "дискусія про увільнення Шагу",
                 "summary_uk": "Зміна посади, новий керівник і фінанси.",
                 "evidence": "Всё идёт по плану шагу он во-первых он МЧС поднял"},
                {"topic": "дискусія про причини зміни посади",
                 "summary_uk": "Міркування про причини кадрового рішення.",
                 "evidence": "По какой причине Как вы считаете Ну я так понимаю"},
                {"topic": "дискусія про корупцію та відповідальність",
                 "summary_uk": "Уточнення причини зміни посади.",
                 "evidence": "Коррупция или Всё идёт по плану просто"},
            ],
        },
    ],
}

ACTUAL_REVIEW_TITLES = [
    "Шойгу и Путин: почему увольнение стало стратегическим шагом",
    "Стратегия без войны: почему Шойгу уволили",
    "Коррупция или план: что движет увольнением",
]


def test_real_ollama_shoigu_titles_must_remain_editorial_review():
    issues = ab_title_issues(ACTUAL_REVIEW_TITLES, SHOIGU_REAL_REPORT)
    assert len(issues) >= 2, issues
    assert any("варіант 1" in item for item in issues)
    assert any("варіант 2" in item for item in issues)


def test_real_transcript_timeline_not_misinterpreted_as_dialogue_count():
    blocks = SHOIGU_REAL_REPORT["blocks"]
    assert len(blocks) == 2
    assert len([topic for block in blocks for topic in block["topics"]]) == 6
    assert blocks[-1]["end_stamp"] == "00:09:34"
    duration_seconds = 9 * 60 + 53
    last_subtitle_second = 9 * 60 + 34
    # Two verified analysis windows != all seconds in the video verified.
    assert duration_seconds - last_subtitle_second == 19


def test_evidence_outline_keeps_six_source_topics_without_claiming_unique_stories():
    outline = evidence_outline_text(SHOIGU_REAL_REPORT)
    for term in ("причина увольнения Шойгу", "корупція в російській армії",
                 "дискусія про увільнення Шагу"):
        assert term in outline
    # The outline repeats one cluster; no "six independent dialogues" inference.
    assert outline.count("ТЕМА:") == 6


def test_all_source_topics_can_be_preserved_without_silent_truncation():
    original = "У цьому відео обговорюють зміну посади Шойгу."
    text, omitted = preserve_outline_topics(
        original, SHOIGU_REAL_REPORT, max_body_bytes=3500, max_topic_bullets=24,
    )
    assert omitted == []
    assert "Інші підтверджені теми" in text
    assert "корупція в російській армії" in text
