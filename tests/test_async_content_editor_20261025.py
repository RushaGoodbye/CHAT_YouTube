"""The SEO editor must remain responsive on a slow YouTube API and preserve user drafts."""
import ast
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _finish(window, app, timeout=8):
    deadline = time.monotonic() + timeout
    while getattr(window, "_content_editor_worker", None) is not None:
        if time.monotonic() > deadline:
            raise AssertionError("SEO editor worker timed out")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_editor_youtube_metadata_is_background_only():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    main = next(
        n for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == "MainWindow"
    )
    method = next(
        n for n in main.body
        if isinstance(n, ast.FunctionDef) and n.name == "edit_content_package"
    )
    task = next(
        n for n in method.body
        if isinstance(n, ast.FunctionDef) and n.name == "task"
    )
    assert not any(
        isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
        for n in ast.walk(task)
    )
    text = ast.get_source_segment(source, method)
    assert "LocalToolWorker(task, self)" in text
    assert "sqlite3.connect(str(db_path), timeout=15)" in text
    assert "worker_conn.close()" in text
    assert "record_quota_units(worker_conn" in text
    assert "running.isRunning()" in text
    assert "self._show_content_package_editor(metadata)" in text


def test_editor_slow_youtube_request_does_not_hang_or_duplicate(
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
                    "title": "УКРАЇНСЬКИЙ ЕФІР",
                    "description": "Зміст стріму",
                    "tags": ["РАША ГУДБАЙ"],
                },
            }], 1)

    monkeypatch.setattr(ui, "YouTubeClient", SlowClient)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        video_id = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", "Existing", "public", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: [video_id],
        )
        shown = []
        monkeypatch.setattr(
            window, "_show_content_package_editor",
            lambda data: shown.append(data),
        )
        started = time.monotonic()
        window.edit_content_package()
        assert time.monotonic() - started < 0.15
        worker = window._content_editor_worker
        window.edit_content_package()
        assert window._content_editor_worker is worker
        _finish(window, app)
        assert len(calls) == 1
        assert calls[0][0] == "main"
        assert calls[0][1] != main_thread
        assert calls[0][2] == [video_id]
        assert len(shown) == 1
        assert shown[0]["title"] == "УКРАЇНСЬКИЙ ЕФІР"
    finally:
        worker = getattr(window, "_content_editor_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()


def test_editor_declines_to_replace_draft_changed_during_dialog(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        video_id = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", "Existing", "public", "2026-10-25"),
        )
        window.conn.commit()
        ui.save_optimization_draft(
            window.conn, video_id, "Old draft", "Old description",
            "", [], "draft",
        )
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *args: warnings.append(args[-1]),
        )

        class ConcurrentEdit:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                window.conn.execute(
                    "UPDATE optimization_drafts "
                    "SET new_title=?,updated_at=? WHERE video_id=?",
                    ("Newer operator draft", "2099-01-01T00:00:00Z", video_id),
                )
                window.conn.commit()
                return QDialog.DialogCode.Accepted

            def values(self):
                return ("Stale dialog", "discard", "", [], "draft", [])

        monkeypatch.setattr(ui, "ContentOptimizationDialog", ConcurrentEdit)
        window._show_content_package_editor({
            "video_id": video_id, "profile": "main",
            "title": "Existing", "description": "Before",
            "tags": ["video"],
        })
        title = window.conn.execute(
            "SELECT new_title FROM optimization_drafts WHERE video_id=?",
            (video_id,),
        ).fetchone()[0]
        assert title == "Newer operator draft"
        assert warnings and "не записано" in warnings[-1]
    finally:
        window.close()
