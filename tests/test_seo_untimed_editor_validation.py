"""Qt regression for the real 2026-10-25 local SEO draft screenshot.

No content of the user's TXT or NAS SRT is stored in the repository.
"""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QMessageBox

from rg_youtube_control.ui import ContentOptimizationDialog


TITLE = "ШОЙГУ И КОРРУПЦИЯ: что думают россияне? | РАША ГУДБАЙ"
DESC = (
    "У випуску чат-рулетки ведучий обговорює з росіянами кадрову "
    "перестановку в Міністерстві оборони. Співрозмовники оцінюють "
    "корупцію та відповідальність посадовців. "
) * 4 + (
    "https://links.rginfoua.pp.ua/ "
    "https://donate.rginfoua.pp.ua/ "
    "#РашаГудбай #Шойгу #ЧатРулетка"
)
TAGS = [
    "Шойгу", "увольнение Шойгу", "коррупция",
    "Россия", "мнение россиян", "чат рулетка",
    "РАША ГУДБАЙ", "Минобороны", "Белоусов",
]
VARIANTS = [
    "ШОЙГУ: коррупция или всё по плану?",
    "ШОЙГУ и Путин: что говорят россияне?",
    "ШОЙГУ и Белоусов: почему поменяли министра?",
]


@pytest.mark.parametrize(
    ("generation", "expect_missing_warning"),
    [
        ("local-seo-evidence-0.7.9", False),
        ("manual", True),
    ],
)
def test_untimed_local_draft_does_not_demand_fabricated_chapters(
    qtbot, monkeypatch, generation, expect_missing_warning,
):
    alerts = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, _title, message: alerts.append(str(message)),
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda _parent, _title, message: alerts.append(str(message)),
    )
    dialog = ContentOptimizationDialog(
        TITLE, DESC, "", TAGS, "draft", VARIANTS,
        generation=generation,
    )
    qtbot.addWidget(dialog)

    dialog.validate_package_now()
    assert len(alerts) == 1
    message = alerts[0]
    assert "Технічна перевірка: OK" in message
    assert ("Розділи не заповнені." in message) is expect_missing_warning
    assert ("Розділи не потрібні для локальної SEO-чернетки" in message) is (
        not expect_missing_warning
    )
    assert "Пакет НЕ готовий до застосування на YouTube." in message
    assert "SEO не підтверджено редактором" in message


def test_verified_chapters_still_get_validated_in_local_draft(qtbot):
    dialog = ContentOptimizationDialog(
        TITLE, DESC, "непідтверджені таймкоди", TAGS,
        "draft", VARIANTS, generation="local-seo-evidence-0.7.9",
    )
    qtbot.addWidget(dialog)
    # Optional only suppresses the missing-chapters warning; it must never
    # allow invalid/non-timestamp chapter text through quality checks.
    from rg_youtube_control.optimization import validate_content_package
    title, desc, chapters, tags, _, ab = dialog.values()
    check = validate_content_package(
        title, desc, chapters, tags, ab, chapters_optional=True,
    )
    assert check.errors
