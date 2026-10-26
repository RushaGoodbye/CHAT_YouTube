"""0.7.34: keep full topic evidence, publish only recognized subjects as review draft."""
from pathlib import Path
import pytest

from rg_youtube_control.free_tools import _deterministic_evidence_description


def sample_report(*topics):
    return {"blocks": [{"verified": True, "topics": [
        {"topic": topic, "evidence": quote} for topic, quote in topics
    ]}]}


def test_observed_dagestan_nations_and_identification_no_longer_break_editor():
    report = sample_report(
        ("Идентификация собеседников", "Давай сначала познакомимся"),
        ("Поведение в России и отношение между народами",
         "Мы обсуждаем отношение людей разных народов"),
        ("Критика поведения в Дагестане через случай с бесплатной едой",
         "Я говорил о случае в Дагестане"),
    )
    review = []
    description = _deterministic_evidence_description(
        "Увольнение ШОЙГУ - коррупция или все идет по плану?",
        report, review_topics=review,
    )
    assert "Дагестані" in description
    assert "народів" in description
    assert "співрозмовників" in description
    assert not review
    assert "через випадок з безплатною їдою" not in description


def test_unknown_model_subject_never_becomes_public_prose_but_is_saved_for_review():
    report = sample_report(
        ("Коррупция чиновников", "В этих разговорах обсуждается коррупция"),
        ("Секретный заговор инопланетян", "Мы обсуждали другой вопрос"),
    )
    review = []
    description = _deterministic_evidence_description(
        "Шойгу и коррупция?", report, review_topics=review,
    )
    assert "корупція" in description
    assert "інопланетян" not in description
    assert review == ["Секретный заговор инопланетян"]


def test_direct_strict_editor_still_fails_closed_on_unknown_topic():
    report = sample_report(
        ("Коррупция чиновников", "В этих разговорах обсуждается коррупция"),
        ("Секретный заговор инопланетян", "Мы обсуждали другой вопрос"),
    )
    with pytest.raises(ValueError, match="Verified subjects require editorial review"):
        _deterministic_evidence_description("Шойгу", report)


def test_zero_mapped_subjects_must_not_become_auto_published_seo():
    report = sample_report(("Секретный заговор инопланетян", "Что это было?"))
    review = []
    description = _deterministic_evidence_description(
        "Шойгу", report, review_topics=review,
    )
    assert "інопланетян" not in description
    assert "Потрібна редакторська перевірка" in description
    assert review == [
        "Секретный заговор инопланетян",
        "NO_RECOGNIZED_EDITORIAL_SUBJECT",
    ]
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("Шойгу", report)


def test_missing_quote_blocks_public_description():
    report = sample_report(("Дагестан", ""))
    with pytest.raises(ValueError, match="No verified transcript quotations"):
        _deterministic_evidence_description(
            "Поведінка людей", report, review_topics=[],
        )


def test_generator_uses_review_collector_and_retains_warning_in_draft():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    assert "editorial_unmapped_subjects: list[str] = []" in source
    assert "review_topics=editorial_unmapped_subjects" in source
    assert 'candidate["_editorial_unmapped_subjects"]' in source
    assert "Потрібна редакторська перевірка непізнаних тем" in source
    assert "bool(evidence_report)" in source
