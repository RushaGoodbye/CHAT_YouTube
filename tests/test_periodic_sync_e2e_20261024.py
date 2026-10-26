"""Exercise periodic cross-profile sync in a real Qt worker with isolated SQLite."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_periodic_metadata_worker_sqlite_e2e(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)

    class FakeClient:
        def __init__(self, profile):
            self.profile = profile

        def credentials(self):
            return True

    def fake_sync(client, conn, limit=None):
        conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",
            (f"qa_periodic_{client.profile}", "verified"),
        )
        conn.commit()
        return [{"id": client.profile}]

    monkeypatch.setattr(ui, "YouTubeClient", FakeClient)
    monkeypatch.setattr(ui, "sync_videos", fake_sync)
    monkeypatch.setattr(ui, "sync_upcoming_live_broadcasts", fake_sync)
    monkeypatch.setattr(ui, "today_quota_units", lambda _conn: 0)

    window = ui.MainWindow()
    try:
        window.background_metadata_sync()
        deadline = time.monotonic() + 15
        while getattr(window, "_background_metadata_worker", None) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("Periodic worker never finished")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        for profile in ui.PROFILE_TARGETS:
            value = window.conn.execute(
                "SELECT value FROM settings WHERE key=?", (f"qa_periodic_{profile}",)
            ).fetchone()
            assert value is not None and value[0] == "verified"
    finally:
        worker = getattr(window, "_background_metadata_worker", None)
        if worker is not None:
            worker.wait(10000)
        window.close()
