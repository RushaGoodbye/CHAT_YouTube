"""Live preview must not freeze the UI while YouTube responds slowly."""
import ast
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _drain(window, app, timeout=8):
    deadline = time.monotonic() + timeout
    while getattr(window, "_safe_preview_worker", None) is not None:
        if time.monotonic() > deadline:
            raise AssertionError("preview metadata worker did not finish")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_safe_preview_never_uses_qt_or_gui_sqlite_in_worker():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(
        x for x in tree.body
        if isinstance(x, ast.ClassDef) and x.name == "MainWindow"
    )
    method = next(
        x for x in main.body
        if isinstance(x, ast.FunctionDef)
        and x.name == "preview_safe_optimization"
    )
    task = next(
        x for x in method.body
        if isinstance(x, ast.FunctionDef) and x.name == "task"
    )
    assert not any(
        isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        and n.value.id == "self" for n in ast.walk(task)
    )
    segment = ast.get_source_segment(source, method)
    assert "sqlite3.connect(str(db_path), timeout=15)" in segment
    assert "worker_conn.close()" in segment
    assert "record_quota_units(worker_conn" in segment
    assert "LocalToolWorker(task, self)" in segment
    assert "running.isRunning()" in segment
    assert "self._show_safe_optimization_preview(result)" in segment


def test_safe_preview_background_and_no_duplicate_clicks(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    main_thread = threading.get_ident()
    calls = []
    class SlowClient:
        def __init__(self, profile):
            self.profile = profile

        def video_details_with_request_count(self, ids):
            calls.append((self.profile, threading.get_ident(), list(ids)))
            time.sleep(0.25)
            return ([{
                "id": ids[0],
                "snippet": {
                    "title": "ПУТІН ЗНОВУ БРЕШЕ",
                    "description": "Український стрім і коментарі",
                    "tags": ["РАША ГУДБАЙ"],
                }
            }], 1)

    monkeypatch.setattr(ui, "YouTubeClient", SlowClient)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        video_id = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", "Published", "public", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: [video_id],
        )
        shown = []
        monkeypatch.setattr(
            window, "_show_safe_optimization_preview",
            lambda result: shown.append(result),
        )
        start = time.monotonic()
        window.preview_safe_optimization()
        assert time.monotonic() - start < 0.15
        worker = window._safe_preview_worker
        window.preview_safe_optimization()
        assert window._safe_preview_worker is worker
        _drain(window, app)
        assert len(calls) == 1
        assert calls[0][0] == "main"
        assert calls[0][1] != main_thread
        assert calls[0][2] == [video_id]
        assert len(shown) == 1
        assert shown[0]["video_id"] == video_id
    finally:
        worker = getattr(window, "_safe_preview_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()


def test_safe_preview_discards_result_after_channel_change(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    class SlowClient:
        def __init__(self, profile):
            self.profile = profile

        def video_details_with_request_count(self, ids):
            time.sleep(0.2)
            return ([{"id": ids[0], "snippet": {
                "title": "video", "description": "content", "tags": []
            }}], 1)

    monkeypatch.setattr(ui, "YouTubeClient", SlowClient)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        video_id = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", "Published", "public", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: [video_id],
        )
        shown = []
        monkeypatch.setattr(
            window, "_show_safe_optimization_preview",
            lambda result: shown.append(result),
        )
        window.preview_safe_optimization()
        window.current_profile = "live"
        _drain(window, app)
        assert not shown
    finally:
        worker = getattr(window, "_safe_preview_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()
