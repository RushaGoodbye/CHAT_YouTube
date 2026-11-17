import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.seo_origin import (
    is_unverified_legacy, is_metadata_only, source_label
)
from rg_youtube_control.seo_readiness import ready_for_youtube


def test_old_ai_seo_never_ready_even_with_historic_safe_flag():
    for generation in ("legacy", "", "manual", "local-ai-v3", "seo-v3-claim-first"):
        allowed, problems = ready_for_youtube(
            status="ready", generation=generation, quality_state="editor_approved",
            variants=["Заголовок А про корупцію", "Заголовок Б про війну", "Заголовок В про суд"],
        )
        assert not allowed, generation
        assert any("Старий SEO-пакет" in problem for problem in problems)
        assert is_unverified_legacy(generation)


def test_source_provenance_is_explicit_and_not_inferred_from_claims():
    for value in ("vidiq-reviewed-srt-v1", "manual-reviewed-srt-v1"):
        assert not is_unverified_legacy(value)
        assert source_label(value)
    assert "невідоме" in source_label("legacy")
    assert is_metadata_only("safe-metadata-0.7.6", "safe_metadata")


def test_safe_metadata_original_path_still_working():
    ok, issues = ready_for_youtube(
        status="ready", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants=[], scheduled=False,
    )
    assert ok and not issues
    ok, _ = ready_for_youtube(
        status="draft", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants=[], scheduled=False,
    )
    assert not ok


def test_scheduled_old_seo_cannot_bypass_origin_gate():
    ok, issues = ready_for_youtube(
        status="ready", generation="legacy",
        quality_state="editor_approved", variants=[], scheduled=True,
    )
    assert not ok
    assert any("Старий SEO" in x for x in issues)
    ok, _ = ready_for_youtube(
        status="ready", generation="manual-reviewed-srt-v1",
        quality_state="editor_approved", variants=[], scheduled=True,
    )
    assert ok


def test_editor_requires_explicit_srt_confirmation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control.ui import ContentOptimizationDialog
    app = QApplication.instance() or QApplication([])
    dialog = ContentOptimizationDialog(
        "Тестова назва", "Опис", "", ["тег"],
        "draft", ["А", "Б", "В"], generation="legacy",
    )
    try:
        assert dialog.selected_generation() == "legacy"
        assert "СТАРИЙ SEO" in " ".join(
            x.text() for x in dialog.findChildren(__import__(
                "PySide6.QtWidgets", fromlist=["QLabel"]
            ).QLabel) if x.objectName() == "SeoOriginWarning"
        )
        index = dialog.origin_selector.findData("vidiq-reviewed-srt-v1")
        dialog.origin_selector.setCurrentIndex(index)
        assert dialog.selected_generation() == "legacy"
        dialog.srt_confirm.setChecked(True)
        assert dialog.selected_generation() == "vidiq-reviewed-srt-v1"
    finally:
        dialog.close()
        app.processEvents()
