"""Archive campaign resume must not synchronously probe NAS before first paint."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_archive_resume_only_enqueues_async_stats(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "archive_priority_enabled", lambda _conn: True)
    window = ui.MainWindow()
    scheduled = []
    monkeypatch.setattr(window, "_refresh_archive_stats_async", lambda: scheduled.append(True))
    monkeypatch.setattr(window, "_archive_campaign_stats",
                        lambda: (_ for _ in ()).throw(AssertionError("blocking NAS read")))
    try:
        window.recover_archive_campaign_state()
        assert scheduled == [True]
        assert window._archive_recovery_pending is True
    finally:
        window.close()


def test_archive_resume_uses_completed_stats_without_second_scan(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "archive_priority_enabled", lambda _conn: True)
    window = ui.MainWindow()
    calls = []
    stats = {"main": {"safe_remaining": 2}, "live": {"safe_remaining": 1}}
    monkeypatch.setattr(
        ui, "reconcile_campaign_checkpoint",
        lambda _conn, values: ({"target": "main", "phase": "safe"}, False),
    )
    monkeypatch.setattr(
        window, "_advance_archive_campaign",
        lambda **kwargs: calls.append(kwargs.get("stats_override")),
    )
    try:
        window._archive_recovery_pending = True
        window._complete_archive_recovery(stats)
        assert calls == [stats]
        assert window._archive_recovery_pending is False
    finally:
        window.close()
