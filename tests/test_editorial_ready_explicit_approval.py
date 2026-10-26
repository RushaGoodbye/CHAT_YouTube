"""Qt and pure release checks: human review must be explicit for local SEO.

The original NAS SRT/verified TXT remain untouched; no YouTube requests.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox, QDialog
from rg_youtube_control.seo_readiness import ready_for_youtube
from rg_youtube_control.ui import ContentOptimizationDialog

TITLE = "ШОЙГУ, КОРРУПЦИЯ И БЕЛОУСОВ: что говорят россияне? | РАША ГУДБАЙ"
DESCRIPTION = (
    "Ведучий обговорює кадрові перестановки у міністерстві оборони РФ "
    "та коментарі росіян про корупцію. Учасники висловлюють власні версії "
    "обговорюють відповідальність посадовців, а також призначення Бєлоусова. "
) * 3
TAGS = ["Шойгу", "Белоусов", "коррупция", "Минобороны России",
        "Путин", "чат рулетка", "РАША ГУДБАЙ", "мнение россиян"]
AB = [
    "ШОЙГУ ПОКИНУЛ МИНОБОРОНЫ: коррупция или план?",
    "ШОЙГУ И БЕЛОУСОВ: чего ждут россияне?",
    "ТИМУР ИВАНОВ И ЗАМЕСТИТЕЛИ ШОЙГУ: вопросы коррупции",
]
GENERATION = "local-seo-evidence-0.7.9"


@pytest.mark.parametrize("status,quality,can_publish", [
    ("draft", "review", False),
    ("ready", "review", False),
    ("ready", "safe", False),
    ("ready", "editor_approved", True),
])
def test_local_seo_release_requires_approval_state(status, quality, can_publish):
    ok, reasons = ready_for_youtube(
        status=status, generation=GENERATION,
        quality_state=quality, variants=AB,
    )
    assert ok is can_publish
    if not ok and quality != "editor_approved":
        assert any("редактор" in message for message in reasons)


def test_editor_cannot_become_ready_from_dropdown_without_personal_confirm(
    qtbot, monkeypatch,
):
    dialog = ContentOptimizationDialog(
        TITLE, DESCRIPTION, "", TAGS, "draft", AB,
        generation=GENERATION,
    )
    qtbot.addWidget(dialog)
    ready_idx = dialog.status_combo.findData("ready")
    dialog.status_combo.setCurrentIndex(ready_idx)
    questions = []
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))
    def decline(_parent, _title, _text, buttons, default):
        questions.append((buttons, default))
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", decline)
    dialog._accept_checked()
    assert len(questions) == 1
    assert questions[0][1] == QMessageBox.StandardButton.No
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.editorial_approved is False

    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog._accept_checked()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.editorial_approved is True
    assert not warnings


def test_legacy_safe_metadata_workflow_is_not_regressed():
    ok, reasons = ready_for_youtube(
        status="ready", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants=[],
    )
    assert ok and not reasons


def test_local_seo_unreviewed_draft_remains_blocked_with_3_distinct_ab():
    ok, reasons = ready_for_youtube(
        status="ready", generation=GENERATION,
        quality_state="safe", variants=AB,
    )
    assert not ok
    assert any("схвалено редактором" in reason for reason in reasons)
