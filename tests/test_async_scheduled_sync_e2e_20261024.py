"""End-to-end offline scheduled-sync thread/SQLite test with a fake API."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_scheduled_sync_uses_isolated_connection(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)

    class FakeClient:
        def __init__(self, profile):
            self.profile = profile

        def credentials(self):
            return object()

    def fake_sync(client, conn):
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (f"worker_sync_{client.profile}", "ok"),
        )
        conn.commit()
        return [{"profile": client.profile}]

    monkeypatch.setattr(ui, "YouTubeClient", FakeClient)
    monkeypatch.setattr(ui, "sync_upcoming_live_broadcasts", fake_sync)
    monkeypatch.setattr(ui, "quota_exhausted", lambda _conn: False)
    monkeypatch.setattr(ui, "today_quota_units", lambda _conn: 0)

    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        window.sync_upcoming_streams_startup()
        deadline = time.monotonic() + 10
        while getattr(window, "_upcoming_sync_worker", None) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("Background scheduled sync did not finish")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        for profile in ui.PROFILE_TARGETS:
            result = window.conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (f"worker_sync_{profile}",),
            ).fetchone()
            assert result is not None and result[0] == "ok"
    finally:
        worker = getattr(window, "_upcoming_sync_worker", None)
        if worker is not None:
            worker.wait(10000)
        window.close()
