"""Headless GUI smoke; run only in PySide6-enabled desktop CI."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from rg_youtube_control import seo_v2_ui


def test_install_preview_tab_keeps_legacy_tabs_unchanged():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.tabs = QTabWidget(window)
    window.tabs.addTab(QTabWidget(), "Оптимізація")
    seo_v2_ui.install_seo_v2_preview(window)
    assert window.tabs.count() == 2
    assert window.tabs.tabText(0) == "Оптимізація"
    assert window.tabs.tabText(1) == "SEO v2"
    view = window.tabs.widget(1)
    assert view._start.isEnabled() is False
    assert view._thread is None
    window.close()
    assert app is not None


def test_preview_selection_requires_explicit_start(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = seo_v2_ui.SEOv2PreviewTab()
    chosen = tmp_path / "clip.srt"
    chosen.write_text("1\n00:00:00,000 --> 00:00:01,000\nТекст.\n", encoding="utf-8")
    window._set_files([chosen])
    assert window._start.isEnabled()
    assert window._thread is None
    assert window._files == [chosen]
    window.close()
    assert app is not None


def test_worker_writes_read_only_reports_and_displays_seo(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "input.srt"
    original = "1\n00:00:00,000 --> 00:00:01,000\nРозмова.\n"
    source.write_text(original, encoding="utf-8")
    output = tmp_path / "results"
    output.mkdir()
    def fake_generate(_source, _candidate, independent_review=None):
        assert independent_review is not None
        return {
            "status": "REVIEW_REQUIRED",
            "evidence": {"accepted": [{"quote": "Розмова."}]},
            "draft": {
                "title": "Нова назва", "title_variants": ["A", "B", "C"],
                "description": "Нова SEO-чернетка", "tags": ["тег"],
            },
            "publication_allowed": False,
        }
    monkeypatch.setattr(seo_v2_ui, "generate_universal_seo", fake_generate)
    worker = seo_v2_ui._SEOv2Worker([source], output)
    messages = []
    worker.line.connect(messages.append)
    worker.run()
    assert any("Нова назва" in message for message in messages)
    assert (output / "input.seo_v2_review.json").exists()
    assert source.read_text("utf-8") == original
    assert (output / "_summary.json").exists()
    assert app is not None
