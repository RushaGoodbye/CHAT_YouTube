"""Zero-quota third-party enrichment must reject duplicates, never invent facts."""

from rg_youtube_control.seo_free_quality import (
    _event_signature, repeated_ab_event_pairs,
)
from rg_youtube_control.dialogue_seo import ab_title_issues


def test_rapidfuzz_catches_same_subject_with_reordered_words():
    variants = [
        "Корупція та Шойгу: що кажуть люди?",
        "Шойгу та корупція: що говорять люди?",
        "Зростання цін на бензин: що кажуть водії?",
    ]
    assert (0, 1) in repeated_ab_event_pairs(variants)
    assert any(
        "1 і 2 повторюють один сюжетний гачок" in reason
        for reason in ab_title_issues(variants)
    )


def test_distinct_verified_topics_are_not_called_duplicates():
    variants = [
        "Бензин на АЗС: що кажуть водії?",
        "Мобілізація в регіоні: які оцінки звучать?",
        "Зарплати та пенсії: як люди оцінюють доходи?",
    ]
    assert repeated_ab_event_pairs(variants) == []


def test_single_shared_protagonist_is_not_duplicate_story():
    variants = [
        "Шойгу та корупція: що кажуть люди?",
        "Шойгу та стратегія: які оцінки військових?",
        "Шойгу та кадрові зміни: чому згадують посаду?",
    ]
    assert repeated_ab_event_pairs(variants) == []


def test_similarity_never_proves_or_creates_transcript_evidence():
    from rg_youtube_control.free_tools import _verified_source_ab_titles
    assert _verified_source_ab_titles({"blocks": []}, "Бензин") == []
    assert len(_event_signature("Бензин та корупція")) >= 2
