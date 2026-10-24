"""Exercise all SQLite-heavy tabs with a synthetic large database."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_large_database_tabs_remain_responsive(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui
    from scripts.qa_seed_startup_db import seed

    data_dir = tmp_path / "app"
    seed(data_dir / "rg_youtube_control.db")
    monkeypatch.setattr(ui, "app_data_dir", lambda: data_dir)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        window.show()
        for index in (1, 2, 3, 6):
            started = time.perf_counter()
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            elapsed = time.perf_counter() - started
            assert elapsed < 25.0, f"Tab {index} blocked Qt for {elapsed:.1f}s"
        assert window.video_table.rowCount() > 0
        assert window.optimization_table.rowCount() > 0
    finally:
        window.close()
