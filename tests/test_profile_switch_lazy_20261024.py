"""Channel switch should never rebuild all heavy hidden Qt tables."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_profile_switch_defers_hidden_tables(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        called = []
        for name in (
            "reload_videos",
            "reload_optimization_queue",
            "reload_comments",
            "reload_action_log",
        ):
            monkeypatch.setattr(
                window, name, lambda name=name: called.append(name)
            )
        window._activate_profile("live")
        assert not called, "Profile switch must not populate tables inline"
        app.processEvents()
        assert called == ["reload_videos"], called
        assert not (window._lazy_loaded_tabs & {2, 3, 6})

        window.tabs.setCurrentIndex(2)
        app.processEvents()
        assert called == ["reload_videos", "reload_optimization_queue"]
        window.tabs.setCurrentIndex(3)
        app.processEvents()
        assert called[-1] == "reload_comments"
        window.tabs.setCurrentIndex(6)
        app.processEvents()
        assert called[-1] == "reload_action_log"

        # A second switch invalidates all four tables again.
        called.clear()
        window._activate_profile("main")
        app.processEvents()
        assert called == ["reload_action_log"], called
        assert not window._lazy_loaded_tabs & {1, 2, 3}
    finally:
        window.close()
