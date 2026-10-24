"""Startup must paint the home screen before loading hidden large tables."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_hidden_tables_deferred_until_open(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    invoked = []
    window.reload_videos = lambda: invoked.append("videos")
    window.reload_optimization_queue = lambda: invoked.append("optimization")
    window.reload_comments = lambda: invoked.append("comments")
    window.reload_action_log = lambda: invoked.append("actions")
    try:
        assert window.tabs.currentIndex() == 0
        window._startup_load_videos()
        app.processEvents()
        assert invoked == []
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        assert invoked == ["videos"]
        window.tabs.setCurrentIndex(2)
        app.processEvents()
        assert invoked == ["videos", "optimization"]
        window.tabs.setCurrentIndex(6)
        app.processEvents()
        assert invoked == ["videos", "optimization", "actions"]
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        assert invoked.count("videos") == 1
    finally:
        window.close()
