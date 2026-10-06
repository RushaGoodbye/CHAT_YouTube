import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_guided_ui_smoke(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)

    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        assert window.tabs.count() >= 9
        assert window.tabs.tabText(0).startswith("Сьогодні")
        assert window.next_action_button.text()
        assert window.optimization_table.columnCount() == 12
        assert window.advanced_mode is False
        assert window.today_process_frame.isHidden()
        assert window.optimization_process_frame.isHidden()
        assert window.log_sections.count() == 2
    finally:
        window.close()
        app.processEvents()
