from pathlib import Path

from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL
from rg_youtube_control.optimization import (
    normalize_package_tags,
    safe_description_fix,
    validate_content_package,
)


def test_package_tags_are_deduped_and_capped_at_15():
    tags = [f"tag {i}" for i in range(20)] + ["TAG 1", "tag 2"]
    normalized = normalize_package_tags(tags)
    assert len(normalized) == 15
    assert normalized[:3] == ["tag 0", "tag 1", "tag 2"]
    assert len({item.casefold() for item in normalized}) == len(normalized)


def test_package_tags_respect_500_character_limit():
    tags = [("x" * 90) + str(i) for i in range(15)]
    normalized = normalize_package_tags(tags)
    assert len(", ".join(normalized)) <= 500


def test_package_validation_requires_exactly_three_hashtags():
    base = (
        ("Український опис для перевірки пакета. " * 12)
        + f"\n\nУСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n{PROJECT_LINKS_URL}"
        + f"\n\nУСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:\n{DONATE_URL}"
    )
    tags = [f"tag{i}" for i in range(8)]

    normalized = validate_content_package(
        "Тестова назва",
        base + "\n\n#one #two",
        "",
        tags,
        [],
    )
    assert "В описі бажано мати рівно 3 релевантні хештеги." not in normalized.warnings

    fixed = safe_description_fix(base, "Путин и война")
    hashtags = [
        token for token in fixed.after.split()
        if token.startswith("#")
    ]
    assert len(hashtags) == 3

    good = validate_content_package(
        "Тестова назва",
        fixed.after,
        "",
        tags,
        [],
    )
    assert "В описі бажано мати рівно 3 релевантні хештеги." not in good.warnings


def test_ui_normalizes_tags_in_editor_and_apply_paths():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    dialog_start = source.index("class ContentOptimizationDialog")
    dialog_end = source.index("\n\nclass MetricCard", dialog_start)
    dialog = source[dialog_start:dialog_end]
    assert "normalized_tags = normalize_package_tags(tags)" in dialog
    assert "tags = normalize_package_tags([" in dialog

    apply_start = source.index("    def apply_content_package")
    apply_end = source.index("\n    @staticmethod\n    def _dedupe_tags", apply_start)
    apply_block = source[apply_start:apply_end]
    assert "new_tags = normalize_package_tags(" in apply_block
    assert "_strip_timestamp_lines(" in apply_block
    assert "compose_description(" not in apply_block


def test_scheduled_package_normalizes_description_and_tags_before_validation():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _prepare_scheduled_package")
    end = source.index("\n    def audit_scheduled_packages", start)
    block = source[start:end]
    assert "tags = normalize_package_tags(original_package_tags)" in block
    assert "safe_description_fix(description, new_title)" in block

def test_scheduled_stream_package_does_not_warn_about_missing_chapters():
    base = (
        ("Український опис для перевірки запланованого стріму. " * 12)
        + f"\n\nУСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n{PROJECT_LINKS_URL}"
        + f"\n\nУСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:\n{DONATE_URL}"
    )
    description = safe_description_fix(base, "Тестовий стрім").after
    check = validate_content_package(
        "Тестовий стрім",
        description,
        "",
        [f"tag{i}" for i in range(8)],
        ["Варіант 1", "Варіант 2", "Варіант 3"],
        chapters_optional=True,
    )
    assert check.ready
    assert "Розділи не заповнені." not in check.warnings

