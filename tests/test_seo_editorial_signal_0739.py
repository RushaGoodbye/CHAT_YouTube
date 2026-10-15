"""0.7.39 regression: do not turn casual jokes into a public SEO hook."""
from pathlib import Path
import re

from rg_youtube_control.seo_editorial_signal import (
    source_grounded_shoigu_package,
    off_topic_title_warnings,
)
from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.seo_source_alignment import (
    check_title_variants_against_primary_subject,
)

TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
SOURCE = (
    "Какова же реальная причина увольнения Шойгу, коррупция "
    "или всё идёт по плану? По моему мнению, Шойгу и Путин "
    "в хороших отношениях. Обсуждали увольнение Шойгу и "
    "назначение Белоусова министром обороны. Аудит расходов "
    "и финансовые вопросы военной стратегии. Предъявлены "
    "обвинения двум заместителям, Шойгу был не в курсе? "
    "Знаете, что с Тимуром Ивановым и его взятками? "
    "А мой собеседник заметил: классная рубашка, где ты взял её? "
    "Другой участник сказал, что всё идёт по плану."
)


def test_real_episode_has_three_distinct_main_topic_ab_and_specific_description():
    result = source_grounded_shoigu_package(TITLE, SOURCE)
    assert result is not None
    assert result["needs_review"] is True
    assert result["chapters"] == ""
    assert len(result["title_variants"]) == 3
    assert not ab_title_issues(result["title_variants"])
    assert not check_title_variants_against_primary_subject(
        TITLE, [result["title"], *result["title_variants"]],
    ).missing
    assert len({v.casefold() for v in result["title_variants"]}) == 3
    assert all(20 <= len(v) <= 100 for v in result["title_variants"])
    assert len(result["title"]) <= 100
    assert 400 <= len(result["description"]) <= 900
    assert "Бєлоусов" in result["description"]
    assert "Тимура Іванова" in result["description"]
    assert "Шойгу" in result["description"]
    assert "фінансами" in result["description"]
    assert "доведені" not in result["description"]
    assert "рубаш" not in str(result).casefold()
    assert 8 <= len(result["tags"]) <= 15


def test_topic_template_needs_actual_original_evidence_not_model_topic():
    original = (
        "Говорят о кадрах, причинах увольнения Шойгу, "
        "но коррупция не обсуждалась."
    )
    # A single nominal "коррупция не обсуждалась" is not sufficient for
    # a high confidence fact claim. Caller must always be review-only.
    assert source_grounded_shoigu_package(TITLE, "Шойгу." * 100) is None
    assert source_grounded_shoigu_package(
        TITLE, "Чечня и Дагестан. " * 100,
    ) is None
    assert source_grounded_shoigu_package(
        "Мнение о военных расходах", SOURCE,
    ) is None


def test_does_not_invent_belousov_or_ivanov_when_absent():
    source = (
        "Ведущий задаёт вопрос об увольнении Шойгу, "
        "коррупция или план? Что говорит Шойгу о смене поста? "
        "Россияне спорят, что же произошло? "
    ) * 7
    result = source_grounded_shoigu_package(TITLE, source)
    assert result is not None
    assert "Бєлоусов" not in result["description"]
    assert "Іванов" not in result["description"]
    assert "Белоусов" not in " ".join(result["title_variants"])
    assert "Тимур Иванов" not in " ".join(result["tags"])


def test_unrelated_clothing_hooks_blocked_outside_fashion_video():
    variants = [
        "Шойгу и коррупция: почему произошла смена министра?",
        "Шойгу уволили — за рубашку или за план?",
        "Шойгу и Белоусов: как объясняют кадровую перестановку?",
    ]
    warnings = off_topic_title_warnings(TITLE, variants)
    assert warnings == [
        "Варіант 2 просуває випадкову репліку про зовнішність"
    ]
    assert off_topic_title_warnings(
        "Какая рубашка лучше для стрима?", variants,
    ) == []


def test_ui_uses_full_original_transcript_not_model_topic_as_source():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    fn = source.split("    def _generate_local_seo_result(",1)[1]
    fn = fn.split("\n    def ",1)[0]
    assert "source_grounded_shoigu_package(" in fn
    assert "current_title, full_source_text" in fn
    assert fn.index("source_grounded_shoigu_package(") < fn.index(
        "check_title_variants_against_primary_subject("
    )
    assert "off_topic_title_warnings(" in fn
    assert fn.index("stronger_editorial = (") < fn.index(
        "package = generate_seo_package_local("
    )
    assert "if stronger_editorial is None:" in fn
    assert 'package["provider"] = "editorial:original-source-verified"' in fn
