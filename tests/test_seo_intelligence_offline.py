from pathlib import Path
import pytest
from rg_youtube_control.seo_intelligence import (
    audit_package, lexical_similarity, transcript_paths,
)


def test_coverage_with_verbatim_grounded_topics():
    a = audit_package(
        evidence_topics=["паливна криза", "економіка росії"],
        title_variants=["ПАЛИВНА КРИЗА В РОСІЇ", "РОСІЙСЬКА ЕКОНОМІКА", "ЩО ВІДБУВАЄТЬСЯ В РФ?"],
        description="Паливна криза та економіка росії у діалогах.",
        min_coverage=0.5,
    )
    assert a.ready
    assert a.covered_topics == 2


def test_missing_topic_is_not_silently_discarded():
    a = audit_package(
        evidence_topics=["паливна криза", "ситуація на фронті"],
        title_variants=["A", "B", "C"],
        description="Паливна криза в росії.",
        min_coverage=0.5,
    )
    assert not a.ready
    assert "ситуація на фронті" in a.missing_topics


def test_duplicate_ab_titles_are_rejected():
    a = audit_package(
        evidence_topics=["паливна криза"],
        title_variants=["Криза", "криза", "Інший варіант"],
        description="Паливна криза в росії.",
        min_coverage=0.5,
    )
    assert "exactly_three_distinct_titles_required" in a.issues


def test_missing_evidence_cannot_pass():
    a = audit_package(
        evidence_topics=[], title_variants=["A", "B", "C"],
        description="Сильний опис",
    )
    assert not a.ready
    assert "no_verified_topics" in a.issues


def test_exact_file_lookup_does_not_walk_unrelated_directories(tmp_path):
    (tmp_path / "MEitKm687xo.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nтест", encoding="utf-8")
    assert transcript_paths("MEitKm687xo", [tmp_path]) == [tmp_path / "MEitKm687xo.srt"]
    with pytest.raises(ValueError):
        transcript_paths("../../etc", [tmp_path])


def test_lexical_similarity_is_bounded():
    assert lexical_similarity("паливна криза", "паливна криза") == 1.0
    assert lexical_similarity("паливна криза", "інші теми") == 0.0
