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


def test_vidiq_first_seo_ui_and_legacy_generator_disabled(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QPushButton, QFrame
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        cards = window.findChildren(QFrame, "VidIQSeoCard")
        assert len(cards) == 1
        labels = [button.text() for button in cards[0].findChildren(QPushButton)]
        assert "Відкрити vidIQ" in labels
        assert "Редагувати SEO-пакет" in labels
        assert window.advanced_batch_seo_action.isEnabled() is False

        destinations = []
        monkeypatch.setattr(window, "_selected_optimization_video_ids",
                            lambda: ["MEitKm687xo"])
        monkeypatch.setattr(ui.QDesktopServices, "openUrl",
                            lambda url: destinations.append(url.toString()) or True)
        monkeypatch.setattr(window, "_generate_local_seo_result",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                                AssertionError("Legacy generator must never run")))
        window.local_seo_selected()
        assert destinations == ["https://app.vidiq.com/"]
        assert app.clipboard().text() == "https://www.youtube.com/watch?v=MEitKm687xo"
    finally:
        window.close()
        app.processEvents()


def test_compact_vidiq_workspace_selection_state(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QFrame
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        cards = window.findChildren(QFrame, "VidIQSeoCard")
        assert len(cards) == 1
        assert len(cards[0].findChildren(QPushButton)) == 4
        assert window.vidiq_import_btn.text() == "Імпорт із vidIQ"
        assert window.vidiq_review_btn.text() == "Пакет vidIQ · перегляд"
        assert not window.vidiq_edit_package_btn.isEnabled()

        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: ["MEitKm687xo"],
        )
        window._update_vidiq_seo_status()
        assert "MEitKm687xo" in window.vidiq_seo_status.text()
        assert "пакет ще не підготовлено" in window.vidiq_seo_status.text()
        assert window.vidiq_edit_package_btn.isEnabled()
        assert window.vidiq_seo_status.objectName() == "VidIQSeoStatus"

        monkeypatch.setattr(
            window, "_selected_optimization_video_ids", lambda: [],
        )
        window._update_vidiq_seo_status()
        assert not window.vidiq_edit_package_btn.isEnabled()
        assert "Виберіть одне відео" in window.vidiq_seo_status.text()
    finally:
        window.close()
        app.processEvents()
