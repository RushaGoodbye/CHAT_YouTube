"""Non-identifying excerpt-based regression of the MEitKm687xo ASR issue.

The user's original TXT/SRT are intentionally NOT committed to public GitHub.
Only invented representative utterances reproduce the exact failure mode.
"""
from __future__ import annotations

from rg_youtube_control.seo_asr_subjects import shoigu_source_evidence
from rg_youtube_control.seo_editorial_signal import (
    source_grounded_shoigu_package, off_topic_title_warnings,
)
from rg_youtube_control.seo_source_alignment import (
    check_title_against_transcript, check_title_variants_against_primary_subject,
)

TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
ASR_FIXTURE = (
    "Ведущий спрашивает: по какой причине произошло увольнение Шойгу? "
    "Один собеседник думает, что шагу не справлялся с военной стратегией. "
    "Другой говорит: коррупция шагу, значит, надо разобраться в обвинениях. "
    "Обсуждают двух заместителей, Белоусова и кадровое решение Путина. "
    "Говорят про Тимура Иванова, взятки и аудит военных расходов. "
    "Некоторые считают: увольнения шагу и его команды это всё по плану. "
    "Другие уверены, что теперь шагу получил другую должность. "
    "Разговор касается Министерства обороны РФ и ответственности командования. "
    "В конце звучит шутка: классная рубашка, где взяли такую одежду? "
)


def test_mixed_realistic_asr_spellings_enable_grounded_editorial():
    original = ASR_FIXTURE
    proof = shoigu_source_evidence(original)
    assert proof.literal_mentions == 1
    assert proof.contextual_asr_mentions >= 3
    assert proof.source_name_supported
    assert check_title_against_transcript(TITLE, original).passed

    result = source_grounded_shoigu_package(TITLE, original)
    assert result is not None, "Previously 1 exact name failed source.count >= 2"
    assert result["needs_review"] is True
    assert len(result["title_variants"]) == 3
    assert all("ШОЙГУ" in item.upper() for item in result["title_variants"])
    assert not check_title_variants_against_primary_subject(
        TITLE, [result["title"], *result["title_variants"]],
    ).missing
    assert not off_topic_title_warnings(
        TITLE, [result["title"], *result["title_variants"]],
    )
    assert "рубаш" not in str(result).lower()
    assert "одежд" not in str(result).lower()
    assert result["chapters"] == ""
    assert result["asr_name_evidence"]["literal_shoigu"] == 1
    assert result["asr_name_evidence"]["original_transcript_preserved"] is True


def test_wrong_srt_named_subject_still_blocked():
    unrelated = (
        "Собеседники обсуждали ситуацию в Дагестане, Кавказ и призыв в армию. "
        "Спорили про мобилизацию, страх и поведение мигрантов. "
    ) * 8
    assert not shoigu_source_evidence(unrelated).source_name_supported
    assert check_title_against_transcript(TITLE, unrelated).missing == ("Шойгу",)
    assert source_grounded_shoigu_package(TITLE, unrelated) is None


def test_no_proper_name_does_not_turn_ordinary_step_into_shoigu():
    accidental = (
        "Каждому шагу предшествует план, Путин говорил про реформы. "
        "Увольнение и коррупция обсуждаются как общие темы. "
    ) * 12
    assert shoigu_source_evidence(accidental).literal_mentions == 0
    assert not shoigu_source_evidence(accidental).source_name_supported
    assert source_grounded_shoigu_package(TITLE, accidental) is None


def test_one_incidental_literal_name_with_unrelated_context_not_sufficient():
    contaminated = (
        "В подписи один раз упомянут Шойгу, но всё интервью про погоду. "
        "Далее идут обычные реплики о погоде и доме. "
    ) * 2
    assert shoigu_source_evidence(contaminated).literal_mentions >= 1
    assert not shoigu_source_evidence(contaminated).source_name_supported
    assert source_grounded_shoigu_package(TITLE, contaminated) is None


def test_long_word_not_misread_as_named_subject():
    source = ("Шайгумаров обсуждал разные шаги. ") * 40
    assert shoigu_source_evidence(source).literal_mentions == 0
    assert shoigu_source_evidence(source).contextual_asr_mentions == 0
