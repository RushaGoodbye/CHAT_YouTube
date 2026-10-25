"""Regression + real Qt offscreen smoke of the previously broken operator path."""
import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.seo_readiness import (
    exact_video_id_search, ready_for_youtube,
)


def test_old_ready_draft_without_ab_is_not_ready_to_publish():
    ok, why = ready_for_youtube(
        status="ready", generation="local-seo-evidence-0.7.17-batch-qa",
        quality_state="safe", variants="[]",
    )
    assert not ok
    assert any("A/B" in reason for reason in why)


def test_unreviewed_legacy_ready_is_not_published():
    ok, why = ready_for_youtube(
        status="ready", generation="legacy", quality_state="",
        variants='["Перше","Друге","Третє"]',
    )
    assert not ok and why


def test_three_editor_approved_different_topics_enable_release():
    ok, errors = ready_for_youtube(
        status="ready", generation="manual", quality_state="editor_approved",
        variants=[
            "ПОЛІЦІЯ ЛНР ПОВЕРНУЛА МАЙНО: РОЗПОВІДЬ ОЧЕВИДЦЯ",
            "ДЕ ПОДІЛАСЯ ВОДА? СПІВРОЗМОВНИК ПРО ЖИТТЯ В ЛУГАНСЬКУ",
            "ЧОМУ МЕДИКИ ВІДМОВИЛИ ПАЦІЄНТУ? ІСТОРІЯ З ЛІКАРНІ",
        ],
    )
    assert ok and not errors


def test_metadata_only_keeps_safe_no_ab_workflow():
    ok, why = ready_for_youtube(
        status="ready", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants="[]",
    )
    assert ok and not why


def test_scheduled_video_cannot_skip_editorial_title_gate():
    ok, why = ready_for_youtube(
        status="ready", generation="scheduled-import",
        quality_state="", variants=[], scheduled=True,
    )
    assert not ok and any("A/B" in item for item in why)


def test_safe_metadata_scheduled_stream_remains_supported():
    ok, why = ready_for_youtube(
        status="ready", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants=[], scheduled=True,
    )
    assert ok and not why


def test_no_ambiguous_non_video_search_override():
    assert exact_video_id_search("LM0vkW9YoKg") == "LM0vkW9YoKg"
    assert exact_video_id_search("  Ati19utM7Ck  ") == "Ati19utM7Ck"
    assert exact_video_id_search("війна в Росії") == ""
    assert exact_video_id_search("123456789012") == ""


_QT_APP = None


def _app():
    global _QT_APP
    from PySide6.QtWidgets import QApplication
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_editor_does_not_invent_generic_chapters():
    _app()
    from rg_youtube_control.ui import ContentOptimizationDialog
    d = ContentOptimizationDialog(
        "Назва для перевірки", "Зміст обговорення у студії.",
        "", ["поліція", "вода"], "draft",
        ["Назва A", "Назва B", "Назва C"],
    )
    try:
        assert d.chapters_edit.toPlainText() == ""
        assert "00:00 Вступ" not in d.chapters_edit.placeholderText()
        assert d.status_combo.findData("applied") < 0
        assert d.status_combo.currentData() == "draft"
    finally:
        d.close()


def test_editors_cannot_mark_unreviewed_seo_ready(monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from rg_youtube_control.ui import ContentOptimizationDialog
    errors = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, _title, message: errors.append(message),
    )
    d = ContentOptimizationDialog(
        "Війна і відповідальність росіян",
        "Співрозмовники дискутують про події й наслідки війни.",
        "", [
            "чат рулетка", "раша гудбай", "Україна", "Росія",
            "війна", "Путін", "мобілізація", "поліція ЛНР",
        ],
        "draft", [], None, generation="local-seo-evidence-0.7.17-batch-qa",
    )
    try:
        d.status_combo.setCurrentIndex(d.status_combo.findData("ready"))
        d._accept_checked()
        assert d.result() != d.DialogCode.Accepted
        assert errors
    finally:
        d.close()


def test_exact_id_search_resets_both_visible_queues():
    _app()
    from PySide6.QtWidgets import QComboBox, QLineEdit
    from rg_youtube_control.ui import MainWindow
    conn=sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE videos(video_id TEXT,profile TEXT)")
    conn.execute("INSERT INTO videos VALUES('LM0vkW9YoKg','main')")
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
    a=QComboBox();a.addItem("Все","all");a.addItem("Готово","prepared");a.setCurrentIndex(1)
    b=QComboBox();b.addItem("Все","all");b.addItem("Готово","ready");b.setCurrentIndex(1)
    search=QLineEdit();search.setText("LM0vkW9YoKg")
    state={"reloads":0}
    class Bar:
        def showMessage(self,*args): pass
    stub=SimpleNamespace(
        optimization_search=search, optimization_filter=a,
        optimization_status_filter=b, current_profile="main",
        conn=conn, statusBar=lambda: Bar(),
        reload_optimization_queue=lambda: state.__setitem__(
            "reloads",state["reloads"]+1),
    )
    try:
        MainWindow._optimization_search_changed(stub)
        assert a.currentData()=="all" and b.currentData()=="all"
        assert state["reloads"]==1
        assert conn.execute(
            "SELECT value FROM settings WHERE key='optimization_status_filter_main'"
        ).fetchone()[0]=="all"
    finally:
        conn.close()
