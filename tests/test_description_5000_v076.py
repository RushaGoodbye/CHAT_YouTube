from pathlib import Path

import pytest

from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL
from rg_youtube_control.optimization import (
    fit_description_to_youtube_limit,
    safe_description_fix,
    validate_content_package,
)


@pytest.mark.parametrize("target_bytes", [5164, 5405, 5424, 5688, 6167, 6884, 6899])
def test_oversized_cyrillic_description_produces_review_draft(target_bytes):
    title = "ЧАТ РУЛЕТКА: перевірка актуальної теми"
    paragraph = (
        "Докладна розмова про життя, реакції глядачів, "
        "спостереження і коментарі учасників. "
    )
    original = paragraph * 25
    while len(safe_description_fix(original, title).after.encode("utf-8")) <= target_bytes:
        original += paragraph
    fitted = fit_description_to_youtube_limit(original, title)
    assert fitted.needs_review, "Never auto-publish a shortened substantive description."
    assert 0 < fitted.result_bytes <= 5000
    assert fitted.result_bytes == len(fitted.description.encode("utf-8"))
    assert fitted.original_bytes > 5000
    assert "перевірити" in fitted.reason
    assert fitted.description.startswith("Докладна розмова")
    assert fitted.description.count(PROJECT_LINKS_URL) == 1
    assert fitted.description.count(DONATE_URL) == 1
    hashtags = [word for word in fitted.description.split() if word.startswith("#")]
    assert len(hashtags) == 3
    assert len(set(hashtags)) == 3
    check = validate_content_package(
        title, fitted.description, "",
        [f"тема {i}" for i in range(8)], [],
        chapters_optional=True,
    )
    assert check.ready
    assert not any("5000" in error for error in check.errors)


def test_short_description_not_marked_as_review():
    title = "Тестова тема"
    original = "Конкретна інформація про сюжет відео. " * 12
    result = fit_description_to_youtube_limit(original, title)
    assert not result.needs_review
    assert result.description == safe_description_fix(original, title).after
    assert result.result_bytes <= 5000


def test_hashtags_before_footer_do_not_break_truncation():
    title = "Путин и санкции"
    text = "Обговорення конкретних питань та аргументів. " * 105
    text = text[:500] + "\n\n#путін #рашагудбай #чатрулетка\n\n" + text[500:]
    result = fit_description_to_youtube_limit(text, title)
    assert result.needs_review
    assert result.result_bytes <= 5000
    assert result.description.count(PROJECT_LINKS_URL) == 1


def test_0_quota_workflow_keeps_original_and_requires_review_before_publishing():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def prepare_zero_quota_batch")
    end = source.index("\n    def show_quota_planner", start)
    block = source[start:end]
    assert "fit_description_to_youtube_limit" in block
    assert 'quality_state="needs_review"' in block
    assert 'status="draft"' in block
    assert "source_description=str(meta.get(" in block
    assert "safe_description_needs_content_package" in block
    assert "У цьому відео обговорюємо тему, зазначену в назві" not in block
    assert 'if str(row["draft_status"] or "") in {"ready", "applied"}:' in block
    assert 'YouTube Data API: 0' in block
