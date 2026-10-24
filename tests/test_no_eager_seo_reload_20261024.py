"""Startup should not reload SEO database while constructing initial window."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_constructor_never_eagerly_loads_seo_queue(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    invoked = []
    original = ui.MainWindow.reload_optimization_queue

    def record(self, *args, **kwargs):
        invoked.append("reload")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ui.MainWindow, "reload_optimization_queue", record)
    window = ui.MainWindow()
    try:
        assert invoked == [], "Constructing MainWindow must not populate hidden SEO table"
        assert window.tabs.currentIndex() == 0
    finally:
        window.close()
