"""Manual YouTube syncs must never freeze Qt or reuse its SQLite connection."""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _await_completion(window, app, timeout=8):
    deadline = time.monotonic() + timeout
    while getattr(window, "_manual_sync_worker", None) is not None:
        if time.monotonic() > deadline:
            raise AssertionError("Manual synchronization worker did not finish")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_manual_video_full_archive_and_both_channels_sync_off_gui(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "quota_exhausted", lambda _conn: False)
    monkeypatch.setattr(ui, "today_quota_units", lambda _conn: 0)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)

    class FakeClient:
        def __init__(self, profile):
            self.profile = profile

        def credentials(self):
            return object()

    monkeypatch.setattr(ui, "YouTubeClient", FakeClient)
    monkeypatch.setattr(
        ui, "sync_upcoming_live_broadcasts", lambda _client, _conn: []
    )

    main_thread = threading.get_ident()
    calls = []

    def fake_sync(client, conn, *, limit):
        calls.append((client.profile, limit, threading.get_ident()))
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            (f"manual_sync_{client.profile}", str(limit)),
        )
        conn.commit()
        time.sleep(0.17)  # A slow API call must not monopolize the GUI thread.
        return [{"video_id": "QA_ONLY"}]

    monkeypatch.setattr(ui, "sync_videos", fake_sync)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        started = time.monotonic()
        window.sync_video_list()
        assert time.monotonic() - started < 0.14
        worker = window._manual_sync_worker
        assert worker is not None
        window.sync_video_list()  # Duplicate click must not overlap.
        assert window._manual_sync_worker is worker
        _await_completion(window, app)
        assert calls == [("main", 50, calls[0][2])]
        assert calls[0][2] != main_thread

        started = time.monotonic()
        window.sync_full_archive()
        assert time.monotonic() - started < 0.14
        _await_completion(window, app)
        assert calls[1][:2] == ("main", 1000)

        started = time.monotonic()
        window.sync_both_channels()
        assert time.monotonic() - started < 0.14
        _await_completion(window, app)
        assert [profile for profile, limit, _ in calls[2:]] == [
            "main", "live"
        ]
        assert all(thread_id != main_thread for _, _, thread_id in calls)
        assert window.conn.execute(
            "SELECT value FROM settings WHERE key='manual_sync_live'"
        ).fetchone()[0] == "1000"
    finally:
        active = getattr(window, "_manual_sync_worker", None)
        if active is not None:
            active.wait(8000)
        window.close()


def test_manual_sync_has_worker_local_sqlite_and_origin_profile():
    import ast
    from pathlib import Path

    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "MainWindow"
    )
    for method_name in ("sync_video_list", "sync_both_channels", "sync_full_archive"):
        method = next(
            item for item in main.body
            if isinstance(item, ast.FunctionDef) and item.name == method_name
        )
        inner = next(
            item for item in method.body
            if isinstance(item, ast.FunctionDef) and item.name == "task"
        )
        assert not any(
            isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == "self"
            and item.attr in ("conn", "client", "current_profile")
            for item in ast.walk(inner)
        ), method_name
        segment = ast.get_source_segment(source, method)
        assert "worker_conn.close()" in segment
        assert "self._start_manual_sync(" in segment
