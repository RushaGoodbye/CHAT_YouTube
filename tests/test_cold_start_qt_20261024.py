"""Cold-start UI regression using isolated SQLite, no YouTube credentials."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_first_paint_with_fresh_database(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    window = ui.MainWindow()
    try:
        window.show()
        app.processEvents()
        assert window.isVisible()
        assert window.tabs.count() >= 7
        assert (tmp_path / "rg_youtube_control.db").is_file()
    finally:
        window.close()
